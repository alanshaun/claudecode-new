"""
监控Celery Beat定时任务
每15分钟轮询IMAP收件箱
"""
import asyncio
import structlog
from datetime import datetime, timezone

from tasks.celery_app import celery_app
from agent.monitor_agent import monitor_agent
from database.supabase_client import db

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="tasks.monitor_task.poll_inbox_task",
    queue="monitor",
    max_retries=3,
    default_retry_delay=120,
    ignore_result=False,
)
def poll_inbox_task():
    """
    定时任务：每15分钟轮询IMAP收件箱
    识别买家回复，触发微信通知
    """
    logger.info("开始IMAP轮询", time=datetime.now(timezone.utc).isoformat())

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(monitor_agent.poll_inbox())
            logger.info("IMAP轮询完成", **result)
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error("IMAP轮询任务异常", error=str(e))
        return {"new_replies": 0, "errors": 1, "error_detail": str(e)}


@celery_app.task(
    name="tasks.monitor_task.flush_fallback_task",
    queue="default",
    ignore_result=True,
)
def flush_fallback_task():
    """定时任务：将fallback文件中的数据补写到Supabase"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(db.flush_fallback())
            logger.info("fallback数据补写完成")
        finally:
            loop.close()
    except Exception as e:
        logger.error("flush_fallback任务异常", error=str(e))


@celery_app.task(
    name="tasks.monitor_task.cleanup_expired_buyers",
    queue="default",
)
def cleanup_expired_buyers():
    """清理超过30天的买家数据（标记需要重新爬取）"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_cleanup_expired())
        finally:
            loop.close()
    except Exception as e:
        logger.error("清理过期买家数据失败", error=str(e))


async def _async_cleanup_expired():
    """标记超过30天的买家数据"""
    from database.supabase_client import TABLE_SEARCH_RESULTS
    try:
        client = db._get_client()
        from datetime import timedelta
        expire_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = client.table(TABLE_SEARCH_RESULTS)\
            .update({"contact_status": "expired"})\
            .lt("expires_at", expire_date)\
            .neq("contact_status", "replied")\
            .execute()
        count = len(result.data) if result.data else 0
        logger.info("过期买家数据已标记", count=count)
    except Exception as e:
        logger.error("标记过期数据失败", error=str(e))
