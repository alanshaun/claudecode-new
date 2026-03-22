"""
Server酱微信通知封装
文档: https://sct.ftqq.com/
容错: 发送失败不崩溃，降级为站内通知，去重防重复推送
"""
import asyncio
import hashlib
import structlog
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import settings

logger = structlog.get_logger(__name__)

# 通知去重缓存（内存级，防止同一事件重复推送）
_notification_cache: dict[str, datetime] = {}
DEDUP_WINDOW_MINUTES = 30  # 30分钟内同一事件不重复推送


class WeChatNotifier:
    """Server酱微信通知发送器"""

    SERVERCHAN_API = "https://sctapi.ftqq.com/{send_key}.send"
    TIMEOUT = 10

    def __init__(self):
        self.send_key = settings.SERVERCHAN_SEND_KEY

    def _get_dedup_key(self, title: str, content: str) -> str:
        """生成去重key"""
        return hashlib.md5(f"{title}:{content}".encode()).hexdigest()[:12]

    def _is_duplicate(self, dedup_key: str) -> bool:
        """检查是否重复推送"""
        if dedup_key in _notification_cache:
            last_sent = _notification_cache[dedup_key]
            if datetime.now(timezone.utc) - last_sent < timedelta(minutes=DEDUP_WINDOW_MINUTES):
                return True
        return False

    def _mark_sent(self, dedup_key: str):
        """标记已推送"""
        _notification_cache[dedup_key] = datetime.now(timezone.utc)
        # 清理过期缓存（超过1小时的）
        expired = [k for k, v in _notification_cache.items()
                   if datetime.now(timezone.utc) - v > timedelta(hours=1)]
        for k in expired:
            del _notification_cache[k]

    async def send(self, title: str, content: str = "",
                   send_key: Optional[str] = None) -> bool:
        """
        发送微信通知
        失败不抛出异常，返回False
        """
        key = send_key or self.send_key
        if not key:
            logger.debug("Server酱SendKey未配置，跳过微信通知")
            return False

        # 去重检查
        dedup_key = self._get_dedup_key(title, content)
        if self._is_duplicate(dedup_key):
            logger.debug("微信通知去重，跳过重复推送", title=title)
            return False

        url = self.SERVERCHAN_API.format(send_key=key)
        payload = {
            "title": title[:32],  # Server酱标题限制32字符
            "desp": content[:1000] if content else title,
            "short": title[:64],
        }

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.post(url, data=payload)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("data", {}).get("errno") == 0 or result.get("code") == 0:
                        self._mark_sent(dedup_key)
                        logger.info("微信通知发送成功", title=title)
                        return True
                    else:
                        logger.warning("Server酱返回错误", result=result, title=title)
                        return False
                else:
                    logger.warning("Server酱HTTP错误", status=resp.status_code, title=title)
                    return False
        except httpx.TimeoutException:
            logger.warning("Server酱发送超时", title=title)
            return False
        except Exception as e:
            logger.error("Server酱发送异常", error=str(e), title=title)
            return False

    async def notify_search_complete(self, task_id: str, result_count: int):
        """搜索完成通知"""
        title = f"🎯 买家搜索完成！找到 {result_count} 家潜在买家"
        content = (
            f"任务ID: {task_id}\n"
            f"找到买家数量: {result_count}\n"
            f"请前往 GlobalMatch 查看详情并选择发送渠道"
        )
        await self.send(title, content)

    async def notify_reply_received(self, buyer_company: str, buyer_email: str):
        """买家回复通知"""
        title = f"📧 买家 {buyer_company} 回复了你！"
        content = (
            f"买家公司: {buyer_company}\n"
            f"买家邮箱: {buyer_email}\n"
            f"请前往 GlobalMatch 查看回复内容"
        )
        await self.send(title, content)

    async def notify_email_sent(self, sent_count: int, failed_count: int):
        """批量发送完成通知"""
        title = f"✅ 开发信发送完成：成功{sent_count}封，失败{failed_count}封"
        content = (
            f"成功发送: {sent_count} 封\n"
            f"发送失败: {failed_count} 封\n"
            f"GlobalMatch Agent 将持续监控买家回复"
        )
        await self.send(title, content)

    async def notify_error(self, error_type: str, detail: str):
        """错误通知"""
        title = f"⚠️ GlobalMatch 任务异常: {error_type}"
        await self.send(title, detail[:500])


# 全局单例
wechat_notifier = WeChatNotifier()
