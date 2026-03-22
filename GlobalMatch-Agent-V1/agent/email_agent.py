"""
邮件Agent - 生成个性化开发信并通过用户SMTP发送
支持：随机延迟防封、速率限制、断点续发、失败重试
"""
import asyncio
import random
import structlog
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings, EMAIL_RATE_LIMIT_PER_MINUTE, EMAIL_DELAY_MIN, EMAIL_DELAY_MAX
from agent.kimi_client import kimi_client
from database.supabase_client import db, TABLE_SENT_EMAILS, TABLE_SEARCH_RESULTS

logger = structlog.get_logger(__name__)


class EmailAgent:
    """邮件生成与发送Agent"""

    def __init__(self):
        self._sent_count = 0
        self._failed_count = 0
        self._rate_limiter_window_start = time.time()
        self._emails_in_window = 0
        # 自适应速率（收到550/421错误时降速）
        self._current_delay_multiplier = 1.0

    async def send_bulk(self, task_id: str, buyers: list[dict],
                         product_info: dict,
                         channel: str = "email",
                         progress_callback=None) -> dict:
        """
        批量发送开发信
        channel: "email" | "whatsapp" | "both"
        返回: {sent, failed, skipped}
        """
        self._sent_count = 0
        self._failed_count = 0
        skipped = 0

        logger.info("开始批量发送", total=len(buyers), channel=channel)

        for i, buyer in enumerate(buyers):
            # 检查是否已发送（断点续发）
            if await self._is_already_sent(task_id, buyer.get("email", "")):
                logger.debug("跳过已发送", email=buyer.get("email"))
                skipped += 1
                continue

            success = False

            if channel in ("email", "both"):
                if buyer.get("email"):
                    success = await self._send_email(task_id, buyer, product_info)

            if channel in ("whatsapp", "both"):
                if buyer.get("whatsapp"):
                    wa_success = await self._send_whatsapp(task_id, buyer, product_info)
                    success = success or wa_success

            if success:
                self._sent_count += 1
            else:
                self._failed_count += 1

            # 进度回调
            if progress_callback:
                progress = int((i + 1) / len(buyers) * 100)
                await progress_callback(progress, f"发送进度: {i+1}/{len(buyers)}")

            # 速率限制（每分钟最多5封）
            await self._rate_limit()

        result = {
            "sent": self._sent_count,
            "failed": self._failed_count,
            "skipped": skipped,
            "total": len(buyers)
        }
        logger.info("批量发送完成", **result)
        return result

    async def _send_email(self, task_id: str, buyer: dict, product_info: dict) -> bool:
        """发送单封邮件"""
        email = buyer.get("email", "")
        if not email:
            return False

        # 生成个性化邮件内容
        email_content = await kimi_client.generate_email(product_info, buyer)
        subject = email_content.get("subject", "Business Cooperation Inquiry")
        body = email_content.get("body", "")

        # 记录到数据库（pending状态）
        record_id = await self._save_email_record(
            task_id, buyer, email, subject, body, "pending"
        )

        # 重试发送
        for attempt in range(settings.SCRAPER_MAX_RETRIES):
            try:
                await self._smtp_send(email, subject, body)
                # 更新状态为sent
                if record_id:
                    await db.update(TABLE_SENT_EMAILS,
                                    {"id": record_id},
                                    {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()})
                # 更新买家状态
                if buyer.get("id"):
                    await db.update(TABLE_SEARCH_RESULTS,
                                    {"id": buyer["id"]},
                                    {"email_status": "sent",
                                     "last_contacted_at": datetime.now(timezone.utc).isoformat()})
                logger.info("邮件发送成功", email=email)
                return True

            except aiosmtplib.errors.SMTPException as e:
                error_msg = str(e)
                logger.warning("SMTP错误", email=email, error=error_msg, attempt=attempt + 1)

                # 550/421错误自动降速
                if "550" in error_msg or "421" in error_msg:
                    self._current_delay_multiplier = min(self._current_delay_multiplier * 2, 8.0)
                    logger.warning("检测到限速错误，降低发送速率", multiplier=self._current_delay_multiplier)

                if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                    await asyncio.sleep(30 * (attempt + 1))
                else:
                    # 最终失败
                    if record_id:
                        await db.update(TABLE_SENT_EMAILS,
                                        {"id": record_id},
                                        {"status": "failed", "error_message": error_msg[:500]})
                    return False

            except Exception as e:
                logger.error("邮件发送异常", email=email, error=str(e))
                if record_id:
                    await db.update(TABLE_SENT_EMAILS,
                                    {"id": record_id},
                                    {"status": "failed", "error_message": str(e)[:500]})
                return False

        return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=30)
    )
    async def _smtp_send(self, to_email: str, subject: str, body: str):
        """SMTP发送（自动重试）"""
        if not all([settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD]):
            raise ValueError("SMTP配置不完整，请在设置页填写")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
        msg["To"] = to_email

        # 纯文本版本
        text_part = MIMEText(body, "plain", "utf-8")
        msg.attach(text_part)

        # HTML版本
        html_body = body.replace("\n", "<br>")
        html_part = MIMEText(f"<html><body><p>{html_body}</p></body></html>", "html", "utf-8")
        msg.attach(html_part)

        smtp = aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            use_tls=False,
            start_tls=settings.SMTP_USE_TLS,
            timeout=30,
        )
        await smtp.connect()
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        await smtp.send_message(msg)
        await smtp.quit()

    async def _send_whatsapp(self, task_id: str, buyer: dict, product_info: dict) -> bool:
        """发送WhatsApp消息（需要Business API Token）"""
        if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.debug("WhatsApp未配置，跳过")
            return False

        whatsapp_num = buyer.get("whatsapp", "")
        if not whatsapp_num:
            return False

        try:
            import httpx
            product_name = product_info.get("product_name", "our products")
            company = buyer.get("company_name", "")
            message = (f"Hello {company}! We are a Chinese manufacturer of {product_name}. "
                       f"We'd love to discuss a potential partnership. "
                       f"Please feel free to reach out for our catalog and pricing.")

            url = f"https://graph.facebook.com/v17.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
                       "Content-Type": "application/json"}
            payload = {
                "messaging_product": "whatsapp",
                "to": whatsapp_num.replace("+", "").replace(" ", "").replace("-", ""),
                "type": "text",
                "text": {"body": message}
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    logger.info("WhatsApp发送成功", phone=whatsapp_num)
                    return True
                else:
                    logger.warning("WhatsApp发送失败", status=resp.status_code)
                    return False
        except Exception as e:
            logger.error("WhatsApp发送异常", error=str(e))
            return False

    async def _save_email_record(self, task_id: str, buyer: dict,
                                  email: str, subject: str,
                                  body: str, status: str) -> Optional[str]:
        """保存邮件记录到数据库"""
        try:
            record = {
                "task_id": task_id,
                "buyer_id": buyer.get("id"),
                "recipient_email": email,
                "recipient_company": buyer.get("company_name", ""),
                "subject": subject,
                "body": body[:5000],
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await db.insert(TABLE_SENT_EMAILS, record)
            return result.get("id") if result else None
        except Exception as e:
            logger.error("保存邮件记录失败", error=str(e))
            return None

    async def _is_already_sent(self, task_id: str, email: str) -> bool:
        """检查是否已经发送过（断点续发保护）"""
        if not email:
            return False
        try:
            records = await db.select(
                TABLE_SENT_EMAILS,
                {"task_id": task_id, "recipient_email": email, "status": "sent"},
                limit=1
            )
            return len(records) > 0
        except Exception:
            return False

    async def _rate_limit(self):
        """速率限制：每分钟最多5封 + 随机延迟"""
        now = time.time()
        window_elapsed = now - self._rate_limiter_window_start

        if window_elapsed >= 60:
            # 重置窗口
            self._rate_limiter_window_start = now
            self._emails_in_window = 0

        self._emails_in_window += 1

        if self._emails_in_window >= EMAIL_RATE_LIMIT_PER_MINUTE:
            # 等待到下一分钟
            wait_time = 60 - window_elapsed + 1
            logger.debug("速率限制，等待", seconds=wait_time)
            await asyncio.sleep(wait_time)
            self._rate_limiter_window_start = time.time()
            self._emails_in_window = 0

        # 随机延迟（防封）
        delay = random.uniform(EMAIL_DELAY_MIN, EMAIL_DELAY_MAX)
        delay *= self._current_delay_multiplier  # 自适应降速
        await asyncio.sleep(delay)


# 全局单例
email_agent = EmailAgent()
