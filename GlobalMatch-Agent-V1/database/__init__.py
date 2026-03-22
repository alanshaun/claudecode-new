from .supabase_client import db, SupabaseClient, SUPABASE_DDL
from .supabase_client import (
    TABLE_SEARCH_TASKS,
    TABLE_SEARCH_RESULTS,
    TABLE_SENT_EMAILS,
    TABLE_REPLIES,
    TABLE_USER_SETTINGS,
    TABLE_NOTIFICATIONS,
)

__all__ = [
    "db", "SupabaseClient", "SUPABASE_DDL",
    "TABLE_SEARCH_TASKS", "TABLE_SEARCH_RESULTS",
    "TABLE_SENT_EMAILS", "TABLE_REPLIES",
    "TABLE_USER_SETTINGS", "TABLE_NOTIFICATIONS",
]
