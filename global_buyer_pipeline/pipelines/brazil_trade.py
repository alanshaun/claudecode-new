"""
来源4：巴西海关数据
下载：http://www.mdic.gov.br
"""
from typing import Dict, List

from pathlib import Path

from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()


def run(config: Dict) -> int:
    source = "brazil_trade"
    limit = config.get("limit", 999999)
    inserted = 0

    data_dir = Path(__file__).parent.parent / "data"
    csv_files = list(data_dir.glob("brazil*.csv")) if data_dir.exists() else []
    if not csv_files:
        logger.info("无 brazil_trade CSV，跳过")
        return 0

    progress = db.get_progress(source)
    last_offset = progress.get("last_offset", 0) if progress else 0
    existing_keys, existing_emails = db.get_existing_keys()

    try:
        import pandas as pd
        for fp in csv_files[:2]:
            if inserted >= limit:
                break
            df = pd.read_csv(fp, nrows=3000, encoding="utf-8", errors="ignore")
            for _, row in df.iterrows():
                if inserted >= limit:
                    break
                company = str(row.get("razao_social", row.get("company", ""))).strip()
                if not company:
                    continue
                rec = clean_record({
                    "company_name": company,
                    "country": "Brazil",
                    "source": source,
                    "categories": [],
                })
                if rec:
                    new_list = filter_new([rec], existing_keys, existing_emails)
                    if new_list:
                        db.insert_buyers(new_list)
                        inserted += 1
        db.save_progress(source, {"last_offset": last_offset + inserted})
    except Exception as e:
        logger.exception("brazil_trade 异常", error=str(e))

    return inserted
