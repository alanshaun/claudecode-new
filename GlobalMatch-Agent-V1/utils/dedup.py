"""
去重逻辑模块
去重规则：同公司名+同域名视为重复
"""
import re
import structlog
from typing import Optional
from urllib.parse import urlparse

logger = structlog.get_logger(__name__)


def normalize_company_name(name: str) -> str:
    """标准化公司名（去除法律后缀、空格、大小写）"""
    if not name:
        return ""
    # 转小写
    name = name.lower().strip()
    # 移除法律实体后缀
    suffixes = [
        r'\b(ltd\.?|limited|llc|inc\.?|incorporated|corp\.?|corporation|'
        r'co\.?\s*ltd\.?|gmbh|ag|sa|sas|srl|bv|nv|plc|pty|pvt\.?\s*ltd\.?|'
        r'trading|enterprise|group|holdings|international|intl)\b'
    ]
    for suffix_pattern in suffixes:
        name = re.sub(suffix_pattern, "", name, flags=re.IGNORECASE)
    # 移除特殊字符和多余空格
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_domain(url_or_email: str) -> Optional[str]:
    """从URL或邮箱提取域名"""
    if not url_or_email:
        return None
    url_or_email = url_or_email.strip().lower()

    # 从邮箱提取
    if "@" in url_or_email and "/" not in url_or_email:
        parts = url_or_email.split("@")
        if len(parts) == 2:
            return parts[1].strip()

    # 从URL提取
    try:
        if not url_or_email.startswith(("http://", "https://")):
            url_or_email = "http://" + url_or_email
        parsed = urlparse(url_or_email)
        domain = parsed.netloc.lower()
        # 移除www.
        domain = re.sub(r'^www\.', '', domain)
        # 移除端口
        domain = domain.split(":")[0]
        return domain if domain else None
    except Exception:
        return None


def make_dedup_key(company_name: str, website: str = "", email: str = "") -> str:
    """生成去重键（公司名标准化 + 域名）"""
    normalized_name = normalize_company_name(company_name)

    domain = None
    if website:
        domain = extract_domain(website)
    if not domain and email:
        domain = extract_domain(email)

    if normalized_name and domain:
        return f"{normalized_name}::{domain}"
    elif normalized_name:
        return f"name::{normalized_name}"
    elif domain:
        return f"domain::{domain}"
    else:
        return ""


class BuyerDeduplicator:
    """买家数据去重器"""

    def __init__(self):
        self._seen_keys: set[str] = set()
        self._seen_emails: set[str] = set()

    def is_duplicate(self, buyer: dict) -> bool:
        """检查是否重复"""
        company = buyer.get("company_name", "")
        website = buyer.get("website", "")
        email = buyer.get("email", "")

        # 邮箱去重（同一邮箱必须去重）
        if email:
            email_lower = email.lower().strip()
            if email_lower in self._seen_emails:
                return True

        # 公司名+域名去重
        key = make_dedup_key(company, website, email)
        if key and key in self._seen_keys:
            return True

        return False

    def add(self, buyer: dict):
        """添加到已见集合"""
        company = buyer.get("company_name", "")
        website = buyer.get("website", "")
        email = buyer.get("email", "")

        if email:
            self._seen_emails.add(email.lower().strip())

        key = make_dedup_key(company, website, email)
        if key:
            self._seen_keys.add(key)

    def deduplicate(self, buyers: list[dict]) -> list[dict]:
        """去重买家列表，保留先出现的"""
        unique = []
        for buyer in buyers:
            if not self.is_duplicate(buyer):
                unique.append(buyer)
                self.add(buyer)
            else:
                logger.debug("去重跳过", company=buyer.get("company_name", ""))
        logger.info("去重结果", input=len(buyers), output=len(unique), removed=len(buyers) - len(unique))
        return unique

    def reset(self):
        """重置去重状态"""
        self._seen_keys.clear()
        self._seen_emails.clear()


def deduplicate_buyers(buyers: list[dict]) -> list[dict]:
    """便捷函数：对买家列表去重"""
    deduplicator = BuyerDeduplicator()
    return deduplicator.deduplicate(buyers)
