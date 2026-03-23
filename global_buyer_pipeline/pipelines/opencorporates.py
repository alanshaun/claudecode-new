"""
来源7：OpenCorporates
API：https://api.opencorporates.com/v0.4/companies/search
完全免费，无需 Key
"""
import asyncio
import time
from typing import Dict, List

import httpx

from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

API = "https://api.opencorporates.com/v0.4/companies/search"
QUERIES = [
    ("us", "importer"), ("us", "wholesaler"), ("us", "distributor"),
    ("gb", "importer"), ("de", "importer"), ("fr", "importer"),
    ("nl", "wholesaler"), ("in", "importer"), ("au", "distributor"),
    ("ca", "importer"), ("br", "importer"), ("mx", "importer"),
]
COUNTRY_MAP = {"us": "United States", "gb": "United Kingdom", "de": "Germany", "fr": "France", "nl": "Netherlands", "in": "India", "au": "Australia", "ca": "Canada", "br": "Brazil", "mx": "Mexico"}


async def fetch_page(country: str, q: str, page: int) -> List[Dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(API, params={
                "q": q,
                "country_code": country,
                "per_page": 30,
                "page": page,
            })
            if resp.status_code != 200:
                return []
            data = resp.json()
            comps = data.get("results", {}).get("companies", [])
            out = []
            for c in comps:
                co = c.get("company", {}) or {}
                name = (co.get("name") or "").strip()
                if not name:
                    continue
                jur = (co.get("jurisdiction_code") or country).upper()
                country_name = COUNTRY_MAP.get(jur.lower(), jur)
                rec = clean_record({
                    "company_name": name[:500],
                    "country": country_name,
                    "website": (co.get("website") or co.get("homepage_url") or "").strip()[:500] or None,
                    "source": "opencorporates",
                    "categories": [q],
                })
                if rec:
                    out.append(rec)
            return out
        except Exception as e:
            logger.warning("OpenCorporates 请求失败", country=country, q=q, error=str(e))
            return []


async def run(config: Dict) -> int:
    source = "opencorporates"
    limit = config.get("limit", 999999)
    inserted = 0

    progress = db.get_progress(source)
    last_kw = progress.get("last_hs_code") if progress else None
    last_pg = progress.get("last_page", 0) if progress else 0

    start_i = 0
    for i, (country, q) in enumerate(QUERIES):
        kw = f"{country}_{q}"
        if kw == last_kw:
            start_i = i
            break

    existing_keys, existing_emails = db.get_existing_keys()

    for qi in range(start_i, len(QUERIES)):
        if inserted >= limit:
            break
        country, q = QUERIES[qi]
        kw = f"{country}_{q}"
        start_page = last_pg + 1 if kw == last_kw else 1

        for page in range(start_page, 15):
            if inserted >= limit:
                break
            items = await fetch_page(country, q, page)
            if not items:
                break
            new_list = filter_new(items, existing_keys, existing_emails)
            if new_list:
                db.insert_buyers(new_list)
                inserted += len(new_list)
                if inserted % 100 == 0:
                    logger.info("已入库：%d 条，当前来源：%s", inserted, source)
            db.save_progress(source, {"last_hs_code": kw, "last_page": page})
            await asyncio.sleep(0.5)

    return inserted
