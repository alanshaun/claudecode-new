"""
邮件发送Celery任务
"""
import asyncio
import structlog
from datetime import datetime, timezone
from celery.exceptions import SoftTimeLimitExceeded

from tasks.celery_app import celery_app
from config import CELERY_MAX_RETRIES
from database.supabase_client import db, TABLE_SEARCH_TASKS, TABLE_SEARCH_RESULTS
from agent.email_agent import EmailAgent
from utils.wechat_notify import wechat_notifier

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.email_task.send_emails",
    max_retries=CELERY_MAX_RETRIES,
    default_retry_delay=60,
    queue="email",
    acks_late=True,
)
def send_emails(self, task_id: str, buyer_ids: list,
                product_info: dict, channel: str = "email"):
    """
    批量发送开发信任务
    buyer_ids: 买家ID列表
    channel: email | whatsapp | both
    """
    logger.info("邮件发送任务开始", task_id=task_id,
                buyer_count=len(buyer_ids), channel=channel)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _async_send_emails(self, task_id, buyer_ids, product_info, channel)
            )
            return result
        finally:
            loop.close()

    except SoftTimeLimitExceeded:
        logger.warning("邮件发送任务软超时", task_id=task_id)
        return {"status": "timeout", "task_id": task_id}

    except Exception as exc:
        logger.error("邮件发送任务失败", task_id=task_id, error=str(exc))
        retry_delay = 60 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=retry_delay, max_retries=CELERY_MAX_RETRIES)


async def _async_send_emails(task, task_id: str, buyer_ids: list,
                              product_info: dict, channel: str) -> dict:
    """异步发送邮件主逻辑"""

    # 从数据库获取买家信息
    buyers = []
    if buyer_ids:
        for buyer_id in buyer_ids:
            records = await db.select(TABLE_SEARCH_RESULTS, {"id": buyer_id}, limit=1)
            if records:
                buyers.append(records[0])

    if not buyers:
        logger.warning("没有找到买家记录", task_id=task_id)
        return {"status": "no_buyers", "task_id": task_id}

    # 进度回调
    async def progress_callback(progress: int, message: str):
        logger.debug("发送进度", progress=progress, message=message)

    # 执行发送
    email_agent = EmailAgent()
    result = await email_agent.send_bulk(
        task_id=task_id,
        buyers=buyers,
        product_info=product_info,
        channel=channel,
        progress_callback=progress_callback
    )

    # 微信通知
    await wechat_notifier.notify_email_sent(result["sent"], result["failed"])

    logger.info("邮件发送任务完成", task_id=task_id, **result)
    return {"status": "completed", "task_id": task_id, **result}


@celery_app.task(
    bind=True,
    name="tasks.email_task.send_single_email",
    max_retries=CELERY_MAX_RETRIES,
    default_retry_delay=30,
    queue="email",
)
def send_single_email(self, task_id: str, buyer_id: str,
                       product_info: dict, channel: str = "email"):
    """发送单封邮件（用于手动选择单个买家）"""
    return send_emails.apply_async(
        args=[task_id, [buyer_id], product_info, channel]
    )
