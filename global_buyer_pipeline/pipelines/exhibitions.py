"""
来源6：展会名录
Canton Fair、Ambiente、CES 等公开页面
"""
import asyncio
import re
from typing import Dict, List

import httpx

from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

SOURCES = [
    {"url": "https://www.cantonfair.org.cn/en-US/buyers", "country": "China", "source": "canton_fair"},
]


async def scrape_url(url: str, country: str, source_name: str) -> List[Dict]:
    """抓取展会页面提取公司名+国家"""
    out = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            text = resp.text
            # 简单提取：找类似公司名的片段
            for m in re.finditer(r'["\']([A-Z][A-Za-z0-9\s&\.\,\-]{3,80})["\']', text):
                name = m.group(1).strip()
                if len(name) > 5 and not re.match(r"^https?://", name):
                    rec = clean_record({
                        "company_name": name[:500],
                        "country": country,
                        "source": source_name,
                        "categories": ["exhibition"],
                    })
                    if rec:
                        out.append(rec)
    except Exception as e:
        logger.warning("展会抓取失败", url=url, error=str(e))
    return out[:100]


async def run(config: Dict) -> int:
    source = "exhibitions"
    limit = config.get("limit", 999999)
    inserted = 0

    progress = db.get_progress(source)
    last_page = progress.get("last_page", 0) if progress else 0
    existing_keys, existing_emails = db.get_existing_keys()

    for i, s in enumerate(SOURCES):
        if inserted >= limit:
            break
        try:
            items = await scrape_url(s["url"], s["country"], s["source"])
            new_list = filter_new(items, existing_keys, existing_emails)
            if new_list:
                db.insert_buyers(new_list)
                inserted += len(new_list)
                if inserted % 10 == 0:
                    logger.info("已入库：%d 条，当前来源：%s", inserted, source)
            db.save_progress(source, {"last_page": i + 1})
        except Exception as e:
            logger.warning("exhibitions 失败", url=s["url"], error=str(e))
        await asyncio.sleep(2)

    return inserted
