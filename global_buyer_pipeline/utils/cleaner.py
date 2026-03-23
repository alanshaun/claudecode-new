"""数据清洗：标准化 company_name、country，过滤无效数据"""
import re
from typing import Dict, Optional

# 国家代码 → 英文名
COUNTRY_MAP = {
    "CN": "China", "US": "United States", "USA": "United States",
    "DE": "Germany", "GB": "United Kingdom", "UK": "United Kingdom",
    "FR": "France", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
    "IN": "India", "JP": "Japan", "KR": "South Korea", "AU": "Australia",
    "CA": "Canada", "BR": "Brazil", "MX": "Mexico", "RU": "Russia",
    "ZA": "South Africa", "AE": "United Arab Emirates", "SA": "Saudi Arabia",
}

def _is_valid_company(name: str) -> bool:
    """过滤无效公司名"""
    if not name or len(name) < 2 or len(name) > 500:
        return False
    name = name.strip()
    if re.match(r"^[\d\s\-\.]+$", name):
        return False
    if re.search(r"[\u4e00-\u9fff]", name) and len(name) < 4:
        return False
    return True

def standardize_country(c: Optional[str]) -> str:
    """标准化国家为英文名"""
    if not c or not str(c).strip():
        return ""
    raw = str(c).strip().upper()[:2]
    return COUNTRY_MAP.get(raw, str(c).strip())

def clean_record(record: Dict) -> Optional[Dict]:
    """清洗单条记录，无效返回 None"""
    company = (record.get("company_name") or "").strip()
    country = standardize_country(record.get("country") or "")
    if not _is_valid_company(company) or not country:
        return None
    return {
        "company_name": company[:500],
        "country": country[:100],
        "email": (record.get("email") or "").strip()[:500] or None,
        "website": (record.get("website") or "").strip()[:500] or None,
        "categories": record.get("categories") or [],
        "source": (record.get("source") or "").strip()[:100],
    }
