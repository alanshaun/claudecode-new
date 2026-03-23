"""
邮箱补全模块
从 Supabase 中有 website 无 email 的记录中，抓取官网提取邮箱
"""
import random
import time
from urllib.parse import urlparse

import httpx

from database.supabase_client import SupabaseDB
from utils.logger import get_logger

logger = get_logger()
db = SupabaseDB()

EMAIL_RE = __import__("re").compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
CONTACT_PATHS = ["/contact", "/about", "/about-us", "/contact-us", "/en/contact"]


def _extract_emails(html: str) -> list:
    found = EMAIL_RE.findall(html)
    return [e for e in found if "example" not in e.lower() and len(e) < 100][:5]


def extract_from_website(website: str) -> str | None:
    if not website or not website.strip():
        return None
    url = website.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                emails = _extract_emails(resp.text)
                if emails:
                    return emails[0]
            base = f"{urlparse(url).scheme or 'https'}://{urlparse(url).netloc}"
            for path in CONTACT_PATHS:
                time.sleep(random.uniform(1, 3))
                full = base.rstrip("/") + path
                try:
                    r = client.get(full)
                    if r.status_code == 200:
                        emails = _extract_emails(r.text)
                        if emails:
                            return emails[0]
                except Exception:
                    pass
    except Exception as e:
        logger.warning("抓取失败", url=url, error=str(e))
    return None


def run(limit: int = 1000) -> int:
    """
    补全邮箱
    返回：成功补全条数
    """
    updated = 0
    offset = 0
    batch = 50

    while updated < limit:
        buyers = db.get_buyers_without_email(limit=batch, offset=offset)
        if not buyers:
            break
        for b in buyers:
            if updated >= limit:
                break
            try:
                website = (b.get("website") or "").strip()
                if not website:
                    continue
                email = extract_from_website(website)
                if email:
                    db.update_buyer_email(b["id"], email)
                    updated += 1
                    if updated % 50 == 0:
                        logger.info("已补全邮箱：%d 条", updated)
            except Exception as e:
                logger.warning("补全失败", company=b.get("company_name"), error=str(e))
            time.sleep(random.uniform(3, 8))
        offset += batch

    return updated
