"""
FastAPI主应用入口
提供健康检查和API接口
"""
import structlog
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database.supabase_client import db, TABLE_SEARCH_TASKS, TABLE_SEARCH_RESULTS

logger = structlog.get_logger(__name__)

# 配置structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期"""
    logger.info("GlobalMatch-Agent-V1 启动中...")
    # 刷新fallback数据
    try:
        await db.flush_fallback()
    except Exception as e:
        logger.warning("启动时flush_fallback失败", error=str(e))
    yield
    logger.info("GlobalMatch-Agent-V1 关闭")


app = FastAPI(
    title="GlobalMatch-Agent-V1",
    description="全球买家开发AI Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """系统健康检查"""
    redis_ok = False
    supabase_ok = False

    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    try:
        await db.select(TABLE_SEARCH_TASKS, limit=1)
        supabase_ok = True
    except Exception:
        pass

    overall_status = "healthy" if (redis_ok and supabase_ok) else "degraded"
    return {
        "status": overall_status,
        "components": {
            "redis": "ok" if redis_ok else "error",
            "supabase": "ok" if supabase_ok else "error",
        },
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    records = await db.select(TABLE_SEARCH_TASKS, {"task_id": task_id}, limit=1)
    if not records:
        raise HTTPException(status_code=404, detail="任务不存在")
    return records[0]


@app.get("/api/tasks/{task_id}/results")
async def get_task_results(task_id: str, limit: int = 100):
    """获取任务搜索结果"""
    buyers = await db.select(
        TABLE_SEARCH_RESULTS,
        {"task_id": task_id},
        limit=limit,
        order_by="created_at"
    )
    return {"task_id": task_id, "count": len(buyers), "buyers": buyers}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
