"""
Celery应用配置
支持：多队列、软硬超时、自动重试、任务去重、持久化
"""
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中（Worker 需要导入 scrapers 等模块）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from celery import Celery
from celery.schedules import crontab
from config import settings, CELERY_TASK_SOFT_TIME_LIMIT, CELERY_TASK_TIME_LIMIT

# 创建Celery实例
celery_app = Celery(
    "globalmatch",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "tasks.search_task",
        "tasks.email_task",
        "tasks.monitor_task",
    ]
)

# Celery配置
celery_app.conf.update(
    # ---- 序列化 ----
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,

    # ---- 超时 ----
    task_soft_time_limit=CELERY_TASK_SOFT_TIME_LIMIT,  # 30分钟软超时
    task_time_limit=CELERY_TASK_TIME_LIMIT,            # 35分钟硬超时

    # ---- 重试 ----
    task_acks_late=True,                   # 任务完成后才ack，崩溃自动重入队
    task_reject_on_worker_lost=True,       # worker意外崩溃，任务重入队

    # ---- 结果过期 ----
    result_expires=86400 * 7,  # 结果保留7天

    # ---- 并发 ----
    worker_prefetch_multiplier=1,  # 每次只预取1个任务（防内存堆积）
    worker_max_tasks_per_child=50, # 每个子进程处理50个任务后重启（防内存泄漏）

    # ---- 队列路由 ----
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "search": {"exchange": "search", "routing_key": "search"},
        "email": {"exchange": "email", "routing_key": "email"},
        "monitor": {"exchange": "monitor", "routing_key": "monitor"},
    },
    task_default_queue="default",
    task_routes={
        "tasks.search_task.*": {"queue": "search"},
        "tasks.email_task.*": {"queue": "email"},
        "tasks.monitor_task.*": {"queue": "monitor"},
    },

    # ---- Redis连接 ----
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # 无限重试
    broker_transport_options={
        "visibility_timeout": 43200,  # 12小时（长任务不重入队）
        "retry_policy": {
            "timeout": 5.0
        }
    },

    # ---- Beat定时任务 ----
    beat_schedule={
        # 每15分钟轮询一次收件箱
        "poll-inbox-every-15min": {
            "task": "tasks.monitor_task.poll_inbox_task",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "monitor"},
        },
        # 每小时刷新fallback数据
        "flush-fallback-every-hour": {
            "task": "tasks.monitor_task.flush_fallback_task",
            "schedule": crontab(minute=0),
            "options": {"queue": "default"},
        },
    },
)
