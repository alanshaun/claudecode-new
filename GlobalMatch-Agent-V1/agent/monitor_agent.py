"""
邮件回复监控Agent
使用IMAP轮询用户授权的邮箱，识别买家回复
"""
import asyncio
import email
import hashlib
import structlog
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

import aioimaplib
from tenacity import retry, stop_after_attempt, wait_fixed

from config import settings
from database.supabase_client import db, TABLE_SENT_EMAILS, TABLE_REPLIES, TABLE_SEARCH_RESULTS
from utils.wechat_notify import wechat_notifier

logger = structlog.get_logger(__name__)


class MonitorAgent:
    """IMAP邮件监控Agent"""

    def __init__(self):
        self._processed_uids: set[str] = set()  # 内存去重，防止重复处理

    async def poll_inbox(self) -> dict:
        """
        轮询收件箱，识别买家回复
        返回: {new_replies: int, errors: int}
        """
        if not all([settings.IMAP_HOST, settings.IMAP_USER, settings.IMAP_PASSWORD]):
            logger.info("IMAP未配置，跳过监控")
            return {"new_replies": 0, "errors": 0}

        new_replies = 0
        errors = 0

        try:
            imap = await self._connect_imap()
            if not imap:
                return {"new_replies": 0, "errors": 1}

            try:
                # 搜索未读邮件
                await imap.select("INBOX")
                # 搜索最近7天的邮件
                status, messages = await imap.search("UNSEEN")
                if status != "OK":
                    logger.warning("IMAP搜索失败", status=status)
                    return {"new_replies": 0, "errors": 1}

                uids = messages[0].decode().split() if messages[0] else []
                logger.info("IMAP扫描未读邮件", count=len(uids))

                for uid in uids[:50]:  # 每次最多处理50封
                    try:
                        result = await self._process_email(imap, uid)
                        if result:
                            new_replies += 1
                    except Exception as e:
                        logger.error("处理邮件失败", uid=uid, error=str(e))
                        errors += 1

            finally:
                try:
                    await imap.logout()
                except Exception:
                    pass

        except Exception as e:
            logger.error("IMAP监控异常", error=str(e))
            errors += 1

        logger.info("IMAP轮询完成", new_replies=new_replies, errors=errors)
        return {"new_replies": new_replies, "errors": errors}

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    async def _connect_imap(self) -> Optional[aioimaplib.IMAP4_SSL]:
        """连接IMAP服务器（自动重连）"""
        try:
            if settings.IMAP_USE_SSL:
                imap = aioimaplib.IMAP4_SSL(
                    host=settings.IMAP_HOST,
                    port=settings.IMAP_PORT,
                    timeout=30
                )
            else:
                imap = aioimaplib.IMAP4(
                    host=settings.IMAP_HOST,
                    port=settings.IMAP_PORT,
                    timeout=30
                )

            await imap.wait_hello_from_server()
            await imap.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
            logger.info("IMAP连接成功", host=settings.IMAP_HOST)
            return imap
        except Exception as e:
            logger.error("IMAP连接失败", error=str(e))
            raise

    async def _process_email(self, imap: aioimaplib.IMAP4_SSL, uid: str) -> bool:
        """
        处理单封邮件
        返回: True表示是新买家回复
        """
        try:
            # 内存去重
            if uid in self._processed_uids:
                return False

            # 获取邮件内容
            status, data = await imap.fetch(uid, "(RFC822)")
            if status != "OK" or not data:
                return False

            # 解析邮件
            raw_email = data[1]
            if not isinstance(raw_email, bytes):
                return False

            msg = email.message_from_bytes(raw_email)

            from_email = self._decode_header_value(msg.get("From", ""))
            from_name, from_addr = self._parse_from(from_email)
            subject = self._decode_header_value(msg.get("Subject", ""))
            date_str = msg.get("Date", "")
            body = self._extract_body(msg)

            if not from_addr:
                return False

            # 去重检查（同一UID不重复处理）
            email_hash = hashlib.md5(f"{uid}:{from_addr}:{subject}".encode()).hexdigest()
            if email_hash in self._processed_uids:
                return False

            # 匹配是否为买家回复（from_email在sent_emails表中）
            sent_record = await self._find_sent_email(from_addr)
            if not sent_record:
                logger.debug("非买家回复，跳过", from_email=from_addr)
                return False

            # 检查数据库中是否已记录
            existing = await db.select(
                TABLE_REPLIES,
                {"sent_email_id": sent_record["id"]},
                limit=1
            )
            # 简单去重：同一sent_email_id+from_email+subject不重复
            for r in existing:
                if r.get("from_email") == from_addr and r.get("subject") == subject:
                    self._processed_uids.add(email_hash)
                    return False

            # 记录回复
            received_at = self._parse_date(date_str)
            reply_record = {
                "sent_email_id": sent_record["id"],
                "from_email": from_addr,
                "from_name": from_name,
                "subject": subject,
                "body": body[:5000],
                "received_at": received_at,
                "notified": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            saved = await db.insert(TABLE_REPLIES, reply_record)

            # 更新买家状态
            if sent_record.get("buyer_id"):
                await db.update(
                    TABLE_SEARCH_RESULTS,
                    {"id": sent_record["buyer_id"]},
                    {
                        "contact_status": "replied",
                        "reply_received_at": received_at
                    }
                )

            # 微信通知
            company = sent_record.get("recipient_company", from_addr)
            await wechat_notifier.notify_reply_received(company, from_addr)

            # 标记通知已发送
            if saved and saved.get("id"):
                await db.update(TABLE_REPLIES, {"id": saved["id"]}, {"notified": True})

            self._processed_uids.add(email_hash)
            logger.info("新买家回复记录", from_email=from_addr, company=company)
            return True

        except Exception as e:
            logger.error("处理邮件异常", uid=uid, error=str(e))
            return False

    async def _find_sent_email(self, from_email: str) -> Optional[dict]:
        """在已发送记录中查找对应买家"""
        try:
            records = await db.select(
                TABLE_SENT_EMAILS,
                {"recipient_email": from_email.lower().strip(), "status": "sent"},
                limit=1
            )
            return records[0] if records else None
        except Exception as e:
            logger.error("查询发送记录失败", error=str(e))
            return None

    def _decode_header_value(self, value: str) -> str:
        """解码邮件头（处理编码）"""
        if not value:
            return ""
        try:
            parts = decode_header(value)
            decoded_parts = []
            for part, encoding in parts:
                if isinstance(part, bytes):
                    decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
                else:
                    decoded_parts.append(str(part))
            return " ".join(decoded_parts)
        except Exception:
            return str(value)

    def _parse_from(self, from_str: str) -> tuple[str, str]:
        """解析发件人字符串，返回 (name, email)"""
        from_str = from_str.strip()
        if "<" in from_str and ">" in from_str:
            name = from_str[:from_str.index("<")].strip().strip('"')
            addr = from_str[from_str.index("<") + 1:from_str.index(">")].strip().lower()
            return name, addr
        else:
            return "", from_str.lower()

    def _extract_body(self, msg: email.message.Message) -> str:
        """提取邮件正文"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(charset, errors="replace")
                            break
                    except Exception:
                        continue
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
            except Exception:
                body = str(msg.get_payload())
        return body

    def _parse_date(self, date_str: str) -> str:
        """解析邮件日期"""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()


# 全局单例
monitor_agent = MonitorAgent()
