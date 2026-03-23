"""Supabase 客户端：buyers、pipeline_progress"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from utils.dedup import make_key, make_email_key

TABLE_BUYERS = "buyers"
TABLE_PROGRESS = "pipeline_progress"


class SupabaseDB:
    def __init__(self):
        self.client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def get_progress(self, source: str) -> Optional[Dict]:
        try:
            r = self.client.table(TABLE_PROGRESS).select("*").eq("source", source).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
        except Exception:
            pass
        return None

    def save_progress(self, source: str, data: Dict):
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            ex = self.get_progress(source)
            if ex:
                self.client.table(TABLE_PROGRESS).update(data).eq("source", source).execute()
            else:
                data["source"] = source
                self.client.table(TABLE_PROGRESS).insert(data).execute()
        except Exception as e:
            raise e

    def get_existing_keys(self) -> Tuple[Set[str], Set[str]]:
        """返回 (company_country_keys, email_keys)"""
        keys, emails = set(), set()
        try:
            offset, batch = 0, 1000
            while True:
                r = self.client.table(TABLE_BUYERS).select("company_name,country,email").range(
                    offset, offset + batch - 1
                ).execute()
                if not r.data:
                    break
                for row in r.data:
                    keys.add(make_key(row.get("company_name", ""), row.get("country", "")))
                    e = (row.get("email") or "").strip()
                    if e:
                        emails.add(make_email_key(e))
                if len(r.data) < batch:
                    break
                offset += batch
        except Exception:
            pass
        return keys, emails

    def get_buyers_without_email(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        try:
            r = self.client.table(TABLE_BUYERS).select("id,company_name,website,country,email").not_.is_(
                "website", "null"
            ).range(offset, offset + limit - 1).execute()
            data = r.data or []
            return [x for x in data if (x.get("website") or "").strip() and not (x.get("email") or "").strip()]
        except Exception:
            return []

    def insert_buyers(self, records: List[Dict]) -> int:
        if not records:
            return 0
        try:
            r = self.client.table(TABLE_BUYERS).insert(records).execute()
            return len(r.data) if r.data else 0
        except Exception as e:
            raise e

    def update_buyer_email(self, buyer_id: str, email: str):
        self.client.table(TABLE_BUYERS).update({
            "email": email,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", buyer_id).execute()
