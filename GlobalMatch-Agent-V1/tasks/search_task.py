"""
搜索Celery任务
用户关闭浏览器后任务继续在后台运行
"""
import asyncio
import structlog
from datetime import datetime, timezone
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from tasks.celery_app import celery_app
from config import CELERY_MAX_RETRIES
from database.supabase_client import db, TABLE_SEARCH_TASKS, TABLE_SEARCH_RESULTS
from utils.wechat_notify import wechat_notifier
from agent.kimi_client import kimi_client
from agent.search_agent import SearchAgent
from utils.pdf_parser import pdf_parser

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.search_task.run_search",
    max_retries=CELERY_MAX_RETRIES,
    default_retry_delay=60,
    queue="search",
    acks_late=True,
)
def run_search(self, task_id: str, user_query: str,
               target_count: int = 100,
               pdf_path: str = None,
               link_url: str = None):
    """
    后台搜索任务（Celery）
    - 用户关闭浏览器后继续运行
    - 失败自动重试3次（60/120/240秒）
    - 超时返回已有结果
    """
    logger.info("搜索任务开始", task_id=task_id, query=user_query)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _async_search(self, task_id, user_query, target_count, pdf_path, link_url)
            )
            return result
        finally:
            loop.close()

    except SoftTimeLimitExceeded:
        logger.warning("搜索任务软超时", task_id=task_id)
        # 软超时：返回已有结果，不崩溃
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            db.update(TABLE_SEARCH_TASKS,
                      {"task_id": task_id},
                      {"status": "timeout", "updated_at": datetime.now(timezone.utc).isoformat()})
        )
        loop.close()
        return {"status": "timeout", "task_id": task_id}

    except Exception as exc:
        logger.error("搜索任务失败", task_id=task_id, error=str(exc))
        # 更新任务状态
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                db.update(TABLE_SEARCH_TASKS,
                          {"task_id": task_id},
                          {"status": "failed",
                           "error_message": str(exc)[:500],
                           "updated_at": datetime.now(timezone.utc).isoformat()})
            )
            loop.close()
        except Exception:
            pass

        # 重试（间隔递增）
        retry_delay = 60 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=retry_delay,
                         max_retries=CELERY_MAX_RETRIES)


async def _async_search(task, task_id: str, user_query: str,
                         target_count: int, pdf_path: str, link_url: str) -> dict:
    """异步搜索主逻辑"""

    # ---- 更新任务状态为运行中 ----
    await db.update(TABLE_SEARCH_TASKS,
                    {"task_id": task_id},
                    {"status": "running",
                     "updated_at": datetime.now(timezone.utc).isoformat()})

    # ---- 提取产品上下文 ----
    product_context = ""

    if pdf_path:
        logger.info("解析PDF", path=pdf_path)
        pdf_result = pdf_parser.parse(pdf_path)
        if not pdf_result.get("error"):
            product_context = (
                f"产品名: {pdf_result.get('product_name', '')}\n"
                f"规格: {', '.join(pdf_result.get('specs', [])[:5])}\n"
                f"卖点: {', '.join(pdf_result.get('selling_points', [])[:5])}\n"
                f"关键词: {', '.join(pdf_result.get('keywords', [])[:10])}"
            )

    if link_url:
        logger.info("抓取链接", url=link_url)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(link_url, follow_redirects=True)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # 提取正文文本
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    page_text = soup.get_text(separator=" ", strip=True)[:3000]
                    product_context += f"\n\n链接页面内容: {page_text}"
        except Exception as e:
            logger.warning("链接抓取失败", url=link_url, error=str(e))

    # ---- Kimi分析搜索参数 ----
    async def progress_update(progress: int, message: str):
        await db.update(TABLE_SEARCH_TASKS,
                        {"task_id": task_id},
                        {"progress": progress,
                         "updated_at": datetime.now(timezone.utc).isoformat()})

    await progress_update(5, "Kimi AI正在分析产品...")
    search_params = await kimi_client.analyze_product_query(user_query, product_context)

    # 更新任务搜索参数
    await db.update(TABLE_SEARCH_TASKS,
                    {"task_id": task_id},
                    {"keywords": search_params.get("keywords_en", []),
                     "target_countries": search_params.get("target_countries", []),
                     "buyer_types": search_params.get("buyer_types", [])})

    # ---- 执行搜索 ----
    search_agent = SearchAgent(progress_callback=progress_update)
    buyers = await search_agent.search(search_params, target_count)

    # ---- 存入数据库 ----
    await progress_update(90, f"正在保存 {len(buyers)} 条买家数据...")

    if buyers:
        records = [{**buyer, "task_id": task_id,
                    "created_at": datetime.now(timezone.utc).isoformat()}
                   for buyer in buyers]
        inserted = await db.batch_insert(TABLE_SEARCH_RESULTS, records)
        logger.info("买家数据已保存", count=inserted)

    # ---- 更新任务完成 ----
    await db.update(TABLE_SEARCH_TASKS,
                    {"task_id": task_id},
                    {"status": "completed",
                     "progress": 100,
                     "result_count": len(buyers),
                     "completed_at": datetime.now(timezone.utc).isoformat(),
                     "updated_at": datetime.now(timezone.utc).isoformat()})

    # ---- 微信通知 ----
    await wechat_notifier.notify_search_complete(task_id, len(buyers))

    logger.info("搜索任务完成", task_id=task_id, result_count=len(buyers))
    return {"status": "completed", "task_id": task_id, "result_count": len(buyers)}


@celery_app.task(name="tasks.search_task.check_duplicate_task")
def check_duplicate_task(user_id: str, query_hash: str) -> bool:
    """检查是否有重复的搜索任务（防止重复入队）"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        records = loop.run_until_complete(
            db.select(TABLE_SEARCH_TASKS,
                      {"status": "running"},
                      limit=10)
        )
        loop.close()
        # 检查是否有相同query_hash的运行中任务
        for record in records:
            if record.get("query_hash") == query_hash:
                return True
        return False
    except Exception:
        return False
