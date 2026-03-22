"""
邮箱验证工具 - 正则+DNS验证
"""
import re
import asyncio
import structlog
import dns.resolver
from typing import Optional

logger = structlog.get_logger(__name__)

# 邮箱正则（RFC 5322标准子集）
EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+'
    r'@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*'
    r'\.[a-zA-Z]{2,}$'
)

# 无效邮箱域名黑名单
BLACKLISTED_DOMAINS = {
    "example.com", "test.com", "dummy.com", "fake.com",
    "noemail.com", "noreply.com", "donotreply.com",
    "mailinator.com", "guerrillamail.com", "tempmail.com",
    "10minutemail.com", "throwaway.email", "yopmail.com",
    "trashmail.com", "sharklasers.com", "guerrillamailblock.com",
}

# 已知有效邮件服务商（可跳过DNS验证）
KNOWN_VALID_PROVIDERS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "protonmail.com", "zoho.com",
    "163.com", "126.com", "qq.com", "sina.com", "sohu.com",
    "foxmail.com", "yeah.net",
}


def is_valid_email_format(email: str) -> bool:
    """纯格式验证（正则）"""
    if not email or not isinstance(email, str):
        return False
    email = email.strip().lower()
    if len(email) > 254:
        return False
    if not EMAIL_REGEX.match(email):
        return False
    domain = email.split("@")[1]
    if domain in BLACKLISTED_DOMAINS:
        return False
    return True


async def validate_email_dns(email: str) -> bool:
    """DNS MX记录验证（验证域名是否真实接收邮件）"""
    if not is_valid_email_format(email):
        return False

    domain = email.split("@")[1].lower()

    # 已知服务商直接通过
    if domain in KNOWN_VALID_PROVIDERS:
        return True

    try:
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(
            None,
            lambda: dns.resolver.resolve(domain, "MX", lifetime=5)
        )
        return len(records) > 0
    except dns.resolver.NXDOMAIN:
        logger.debug("邮箱域名不存在", domain=domain)
        return False
    except dns.resolver.NoAnswer:
        # 无MX记录，但可能有A记录，降级为格式验证通过
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: dns.resolver.resolve(domain, "A", lifetime=5)
            )
            return True
        except Exception:
            return False
    except Exception as e:
        logger.debug("DNS验证异常，使用格式验证", domain=domain, error=str(e))
        return True  # DNS验证失败时，格式正确也视为有效


def validate_emails_batch(emails: list[str]) -> list[str]:
    """批量格式验证，返回有效邮箱列表"""
    return [email.strip().lower() for email in emails if is_valid_email_format(email.strip())]


async def validate_emails_batch_dns(emails: list[str]) -> list[str]:
    """批量DNS验证（并发，最多20个并发）"""
    valid = []
    semaphore = asyncio.Semaphore(20)

    async def check(email: str) -> Optional[str]:
        async with semaphore:
            if await validate_email_dns(email):
                return email
            return None

    tasks = [check(email) for email in emails if is_valid_email_format(email)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if result and isinstance(result, str):
            valid.append(result)

    return valid


def extract_emails_from_text(text: str) -> list[str]:
    """从文本中提取所有邮箱地址"""
    pattern = r'[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found = re.findall(pattern, text)
    # 格式验证 + 去重
    valid = []
    seen = set()
    for email in found:
        email_lower = email.lower().strip()
        if email_lower not in seen and is_valid_email_format(email_lower):
            seen.add(email_lower)
            valid.append(email_lower)
    return valid
