"""
来源3：印度进出口数据
API：https://tradestat.commerce.gov.in
按 HS 编码查印度进口商
"""
import asyncio
from typing import Dict, List

import httpx

from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

# 印度贸易统计 API（需确认实际端点）
BASE_URL = "https://tradestat.commerce.gov.in/eidb/"


async def run(config: Dict) -> int:
    source = "india_trade"
    limit = config.get("limit", 999999)
    inserted = 0

    progress = db.get_progress(source)
    last_hs = progress.get("last_hs_code") if progress else None
    hs_list = [61, 62, 84, 85, 95]
    start_idx = 0
    if last_hs:
        for i, h in enumerate(hs_list):
            if str(h) == last_hs:
                start_idx = i + 1
                break

    existing_keys, existing_emails = db.get_existing_keys()

    for i in range(start_idx, len(hs_list)):
        if inserted >= limit:
            break
        hs = hs_list[i]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(BASE_URL, params={"hs": hs})
                if resp.status_code != 200:
                    continue
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                items = data.get("data", data) if isinstance(data, dict) else []
                if not isinstance(items, list):
                    items = []
                for row in items[:50]:
                    name = (row.get("importer") or row.get("company") or row.get("name") or "").strip()
                    if name:
                        rec = clean_record({
                            "company_name": name,
                            "country": "India",
                            "source": source,
                            "categories": [str(hs)],
                        })
                        if rec:
                            new_list = filter_new([rec], existing_keys, existing_emails)
                            if new_list:
                                db.insert_buyers(new_list)
                                inserted += 1
            db.save_progress(source, {"last_hs_code": str(hs)})
        except Exception as e:
            logger.warning("india_trade 失败", hs=hs, error=str(e))
        await asyncio.sleep(1)

    return inserted
