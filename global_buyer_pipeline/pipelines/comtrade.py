"""
来源1：UN Comtrade API
官方：https://comtradeapi.un.org
按 HS 编码查全球进口数据（国家级），间隔 1 秒
"""
import asyncio
import time
from typing import Dict, List

import httpx

from config import COMTRADE_API_KEY, COMTRADE_DELAY, HS_CODES
from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

BASE_URL = "https://comtradeapi.un.org/public/v1/get/"


def _flatten_hs() -> List[int]:
    out = []
    for vals in HS_CODES.values():
        for v in vals:
            if isinstance(v, int) and v not in out:
                out.append(v)
    return sorted(out)


async def fetch_comtrade(hs: int) -> List[Dict]:
    """请求单次 HS 的进口数据（中国为出口国）"""
    params = {
        "frequencyCode": "A",
        "typeCode": "C",
        "reporterCode": "all",
        "partnerCode": "156",
        "period": "2024",
        "classificationCode": "HS",
        "customsCode": "C00",
        "flowCode": "M",
    }
    # HS 需补齐到2位
    hs_str = str(hs).zfill(2) if hs < 100 else str(hs)
    params["cmdCode"] = hs_str[:2]

    headers = {}
    if COMTRADE_API_KEY:
        headers["Ocp-Apim-Subscription-Key"] = COMTRADE_API_KEY

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.get(BASE_URL, params=params, headers=headers)
            if resp.status_code != 200:
                logger.warning("Comtrade 请求失败", hs=hs, status=resp.status_code)
                return []
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                return data.get("data", [])
            return []
        except Exception as e:
            logger.warning("Comtrade 异常", hs=hs, error=str(e))
            return []


def _to_buyers(raw: List, hs: int, category: str) -> List[Dict]:
    """将 Comtrade 原始数据转为 buyers 格式"""
    out = []
    seen = set()
    for row in raw:
        rep = (row.get("reporterCode") or row.get("reporterDesc") or "").strip()
        if not rep or rep in seen:
            continue
        seen.add(rep)
        country = rep if len(rep) > 2 else rep
        rec = {
            "company_name": f"HS{hs} Importer - {country}",
            "country": country,
            "email": None,
            "website": None,
            "categories": [str(hs), category],
            "source": "un_comtrade",
        }
        cleaned = clean_record(rec)
        if cleaned:
            out.append(cleaned)
    return out


async def run(config: Dict) -> int:
    """
    执行 Comtrade 管道
    config: { limit, resume }
    返回插入条数
    """
    source = "un_comtrade"
    limit = config.get("limit", 999999)
    inserted = 0

    progress = db.get_progress(source)
    last_hs = progress.get("last_hs_code") if progress else None
    hs_list = _flatten_hs()
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
        cat = next((k for k, v in HS_CODES.items() if hs in v), "other")
        try:
            raw = await fetch_comtrade(hs)
            buyers = _to_buyers(raw, hs, cat)
            new_list = filter_new(buyers, existing_keys, existing_emails)
            if new_list:
                count = db.insert_buyers(new_list)
                inserted += count
                if inserted % 100 == 0:
                    logger.info("已入库：%d 条，当前来源：%s", inserted, source)
            db.save_progress(source, {"last_hs_code": str(hs)})
        except Exception as e:
            logger.exception("Comtrade HS 失败", hs=hs, error=str(e))
        await asyncio.sleep(COMTRADE_DELAY)

    return inserted
