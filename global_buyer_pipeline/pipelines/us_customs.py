"""
来源2：美国海关公开数据
下载：https://usatrade.census.gov
需手动下载 CSV 后放入 data/ 或通过 URL 拉取
"""
from typing import Dict, List

from database.supabase_client import SupabaseDB
from utils.cleaner import clean_record, standardize_country
from utils.dedup import filter_new
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

# 若可公开访问的样例 URL（实际需根据 census.gov 文档调整）
SAMPLE_CSV_URL = "https://api.census.gov/data/timeseries/intltrade/imports"


def run(config: Dict) -> int:
    """
    美国海关管道
    若无 CSV/API，返回 0；有则解析入库
    """
    source = "us_customs"
    limit = config.get("limit", 999999)
    inserted = 0

    try:
        import pandas as pd
    except ImportError:
        logger.warning("pandas 未安装，跳过 us_customs")
        return 0

    progress = db.get_progress(source)
    last_offset = progress.get("last_offset", 0) if progress else 0
    existing_keys, existing_emails = db.get_existing_keys()

    # 尝试从本地 data 目录读取
    try:
        from pathlib import Path
        data_dir = Path(__file__).parent.parent / "data"
        csv_files = list(data_dir.glob("*.csv")) if data_dir.exists() else []
        if not csv_files:
            logger.info("无 us_customs CSV 文件，跳过")
            return 0

        for fp in csv_files[:3]:
            if inserted >= limit:
                break
            try:
                df = pd.read_csv(fp, nrows=5000, encoding="utf-8", errors="ignore")
                for col in ["IMPORTER", "company", "Company Name", "Importer"]:
                    if col in df.columns:
                        break
                else:
                    continue
                name_col = [c for c in df.columns if "name" in c.lower() or "importer" in c.lower()][:1]
                name_col = name_col[0] if name_col else df.columns[0]
                for _, row in df.iterrows():
                    if inserted >= limit:
                        break
                    company = str(row.get(name_col, "")).strip()
                    country = "United States"
                    rec = clean_record({
                        "company_name": company,
                        "country": country,
                        "source": source,
                        "categories": [],
                    })
                    if rec:
                        new_list = filter_new([rec], existing_keys, existing_emails)
                        if new_list:
                            db.insert_buyers(new_list)
                            inserted += 1
            except Exception as e:
                logger.warning("CSV 解析失败", file=str(fp), error=str(e))

        db.save_progress(source, {"last_offset": last_offset + inserted})
    except Exception as e:
        logger.exception("us_customs 异常", error=str(e))

    return inserted
