"""
Supabase数据库操作封装
支持：自动重试、批量写入、本地fallback、断点续传
"""
import json
import asyncio
import structlog
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from supabase import create_client, Client
from config import settings, FALLBACK_DIR

logger = structlog.get_logger(__name__)

# ---- Supabase表名常量 ----
TABLE_SEARCH_TASKS = "search_tasks"
TABLE_SEARCH_RESULTS = "search_results"
TABLE_SENT_EMAILS = "sent_emails"
TABLE_REPLIES = "replies"
TABLE_USER_SETTINGS = "user_settings"
TABLE_NOTIFICATIONS = "notifications"


class SupabaseClient:
    """Supabase操作封装，含容错和重试"""

    def __init__(self):
        self._client: Optional[Client] = None
        self._fallback_file = FALLBACK_DIR / "fallback_writes.jsonl"
        self._init_client()

    def _init_client(self):
        """初始化Supabase客户端"""
        try:
            self._client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
            )
            logger.info("Supabase客户端初始化成功")
        except Exception as e:
            logger.error("Supabase客户端初始化失败", error=str(e))
            self._client = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._init_client()
        if self._client is None:
            raise ConnectionError("Supabase连接不可用")
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def insert(self, table: str, data: dict) -> Optional[dict]:
        """插入单条记录，失败写入本地fallback"""
        try:
            client = self._get_client()
            result = client.table(table).insert(data).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error("Supabase写入失败，写入fallback", table=table, error=str(e))
            self._write_fallback(table, data)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def upsert(self, table: str, data: dict, on_conflict: str = "id") -> Optional[dict]:
        """插入或更新记录"""
        try:
            client = self._get_client()
            result = client.table(table).upsert(data, on_conflict=on_conflict).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error("Supabase upsert失败", table=table, error=str(e))
            self._write_fallback(table, data)
            raise

    async def batch_insert(self, table: str, records: list[dict], batch_size: int = 50) -> int:
        """批量插入，每批50条，避免超时，返回成功插入数"""
        total_inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            try:
                client = self._get_client()
                result = client.table(table).insert(batch).execute()
                inserted = len(result.data) if result.data else 0
                total_inserted += inserted
                logger.info("批量写入成功", table=table, batch=i // batch_size + 1, count=inserted)
                await asyncio.sleep(0.1)  # 避免速率限制
            except Exception as e:
                logger.error("批量写入失败，写入fallback", table=table, batch_num=i // batch_size, error=str(e))
                for record in batch:
                    self._write_fallback(table, record)
        return total_inserted

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def select(self, table: str, filters: Optional[dict] = None,
                     limit: Optional[int] = None, order_by: Optional[str] = None,
                     order_desc: bool = True) -> list[dict]:
        """查询记录"""
        try:
            client = self._get_client()
            query = client.table(table).select("*")
            if filters:
                for key, value in filters.items():
                    if isinstance(value, list):
                        query = query.in_(key, value)
                    else:
                        query = query.eq(key, value)
            if order_by:
                query = query.order(order_by, desc=order_desc)
            if limit:
                query = query.limit(limit)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error("Supabase查询失败", table=table, error=str(e))
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def update(self, table: str, filters: dict, data: dict) -> list[dict]:
        """更新记录"""
        try:
            client = self._get_client()
            query = client.table(table).update(data)
            for key, value in filters.items():
                query = query.eq(key, value)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error("Supabase更新失败", table=table, error=str(e))
            return []

    async def delete(self, table: str, filters: dict) -> bool:
        """删除记录"""
        try:
            client = self._get_client()
            query = client.table(table).delete()
            for key, value in filters.items():
                query = query.eq(key, value)
            query.execute()
            return True
        except Exception as e:
            logger.error("Supabase删除失败", table=table, error=str(e))
            return False

    def _write_fallback(self, table: str, data: dict):
        """写入本地fallback文件，恢复后补写Supabase"""
        try:
            record = {
                "table": table,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "written": False
            }
            with open(self._fallback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("fallback文件写入失败", error=str(e))

    async def flush_fallback(self):
        """将fallback文件中未写入的记录补写到Supabase"""
        if not self._fallback_file.exists():
            return
        try:
            lines = self._fallback_file.read_text(encoding="utf-8").strip().splitlines()
            remaining = []
            for line in lines:
                try:
                    record = json.loads(line)
                    if not record.get("written"):
                        client = self._get_client()
                        client.table(record["table"]).insert(record["data"]).execute()
                        record["written"] = True
                        logger.info("fallback记录补写成功", table=record["table"])
                    remaining.append(json.dumps(record, ensure_ascii=False))
                except Exception as e:
                    logger.error("fallback记录补写失败", error=str(e))
                    remaining.append(line)
            with open(self._fallback_file, "w", encoding="utf-8") as f:
                f.write("\n".join(remaining) + "\n" if remaining else "")
        except Exception as e:
            logger.error("flush_fallback失败", error=str(e))


# ---- 数据库表结构DDL（首次运行执行）----
SUPABASE_DDL = """
-- 搜索任务表
CREATE TABLE IF NOT EXISTS search_tasks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    task_id TEXT UNIQUE NOT NULL,
    user_query TEXT NOT NULL,
    keywords JSONB,
    target_countries JSONB,
    buyer_types JSONB,
    target_count INTEGER DEFAULT 100,
    status TEXT DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 搜索结果/买家数据表
CREATE TABLE IF NOT EXISTS search_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    task_id TEXT REFERENCES search_tasks(task_id),
    company_name TEXT NOT NULL,
    country TEXT,
    website TEXT,
    email TEXT,
    whatsapp TEXT,
    facebook TEXT,
    linkedin TEXT,
    categories JSONB,
    source TEXT,
    contact_status TEXT DEFAULT 'new',
    email_status TEXT DEFAULT 'not_sent',
    last_contacted_at TIMESTAMPTZ,
    reply_received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

-- 发送邮件记录表
CREATE TABLE IF NOT EXISTS sent_emails (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    task_id TEXT,
    buyer_id UUID REFERENCES search_results(id),
    recipient_email TEXT NOT NULL,
    recipient_company TEXT,
    subject TEXT,
    body TEXT,
    status TEXT DEFAULT 'pending',
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    message_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 回复记录表
CREATE TABLE IF NOT EXISTS replies (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    sent_email_id UUID REFERENCES sent_emails(id),
    from_email TEXT NOT NULL,
    from_name TEXT,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMPTZ,
    notified BOOLEAN DEFAULT FALSE,
    notification_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 用户设置表
CREATE TABLE IF NOT EXISTS user_settings (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    setting_key TEXT UNIQUE NOT NULL,
    setting_value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 站内通知表
CREATE TABLE IF NOT EXISTS notifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    related_id TEXT,
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_search_results_task_id ON search_results(task_id);
CREATE INDEX IF NOT EXISTS idx_search_results_email ON search_results(email);
CREATE INDEX IF NOT EXISTS idx_sent_emails_task_id ON sent_emails(task_id);
CREATE INDEX IF NOT EXISTS idx_sent_emails_recipient ON sent_emails(recipient_email);
CREATE INDEX IF NOT EXISTS idx_replies_from_email ON replies(from_email);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
"""


# 全局单例
db = SupabaseClient()
