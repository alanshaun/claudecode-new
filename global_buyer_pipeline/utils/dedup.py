"""去重逻辑"""
from typing import Dict, List, Set

def make_key(company_name: str, country: str) -> str:
    return f"{(company_name or '').strip().lower()}|||{(country or '').strip().lower()}"

def make_email_key(email: str) -> str:
    return (email or "").strip().lower()

def filter_new(candidates: List[Dict], existing_keys: Set[str], existing_emails: Set[str]) -> List[Dict]:
    """过滤已存在的候选人"""
    out = []
    for r in candidates:
        key = make_key(r.get("company_name", ""), r.get("country", ""))
        if key in existing_keys:
            continue
        email = (r.get("email") or "").strip()
        if email and make_email_key(email) in existing_emails:
            continue
        existing_keys.add(key)
        if email:
            existing_emails.add(make_email_key(email))
        out.append(r)
    return out
