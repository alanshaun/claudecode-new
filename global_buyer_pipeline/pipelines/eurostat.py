"""
来源5：欧盟贸易数据
API：https://ec.europa.eu/eurostat
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

# Eurostat REST API 示例
BASE_URL = "https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/"


async def run(config: Dict) -> int:
    source = "eurostat"
    limit = config.get("limit", 999999)
    inserted = 0

    progress = db.get_progress(source)
    last_page = progress.get("last_page", 0) if progress else 0
    existing_keys, existing_emails = db.get_existing_keys()

    eu_countries = ["DE", "FR", "IT", "ES", "NL", "BE", "PL", "AT", "PT"]
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            for i, cc in enumerate(eu_countries):
                if inserted >= limit:
                    break
                try:
                    # Eurostat 需具体数据流，此处用占位
                    resp = await client.get(BASE_URL)
                    if resp.status_code != 200:
                        continue
                    country_name = {"DE": "Germany", "FR": "France", "IT": "Italy"}.get(cc, cc)
                    rec = clean_record({
                        "company_name": f"EU Importer - {country_name}",
                        "country": country_name,
                        "source": source,
                        "categories": ["EU"],
                    })
                    if rec:
                        new_list = filter_new([rec], existing_keys, existing_emails)
                        if new_list:
                            db.insert_buyers(new_list)
                            inserted += 1
                    db.save_progress(source, {"last_page": i})
                except Exception as e:
                    logger.warning("eurostat 失败", country=cc, error=str(e))
                await asyncio.sleep(1)
    except Exception as e:
        logger.exception("eurostat 异常", error=str(e))

    return inserted
