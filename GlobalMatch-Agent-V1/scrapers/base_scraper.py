"""
爬虫基类 - 所有爬虫继承此类
提供：Playwright初始化、随机UA、反爬延迟、重试、内存保护
"""
import asyncio
import random
import structlog
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from config import settings, USER_AGENTS
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)


class BaseScraper:
    """爬虫基类"""

    SOURCE_NAME = "base"
    MAX_RETRIES = 3
    PAGE_TIMEOUT = 30000  # 30秒

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def get_page_with_playwright(self, url: str,
                                        wait_for: Optional[str] = None,
                                        extra_delay: float = 0) -> Optional[str]:
        """
        用Playwright获取页面HTML
        自动：随机UA、随机延迟、超时处理、内存保护
        """
        for attempt in range(self.MAX_RETRIES):
            browser = None
            context = None
            page = None
            try:
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=settings.PLAYWRIGHT_HEADLESS,
                        args=[
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-accelerated-2d-canvas",
                            "--disable-gpu",
                            "--no-first-run",
                            "--no-zygote",
                            "--disable-background-networking",
                            "--disable-default-apps",
                        ]
                    )
                    context = await browser.new_context(
                        user_agent=self.get_random_ua(),
                        viewport={"width": 1280, "height": 800},
                        locale="en-US",
                        java_script_enabled=True,
                    )
                    page = await context.new_page()
                    page.set_default_timeout(self.PAGE_TIMEOUT)

                    # 随机延迟（防反爬）
                    delay = random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX)
                    if extra_delay:
                        delay += extra_delay
                    await asyncio.sleep(delay)

                    response = await page.goto(url, wait_until="domcontentloaded")

                    # 检查反爬（403/429/验证码）
                    if response and response.status in (403, 429):
                        logger.warning("反爬触发，切换数据源",
                                       source=self.SOURCE_NAME, url=url,
                                       status=response.status)
                        return None

                    if wait_for:
                        try:
                            await page.wait_for_selector(wait_for, timeout=10000)
                        except Exception:
                            pass

                    html = await page.content()
                    return html

            except asyncio.TimeoutError:
                logger.warning("页面超时", source=self.SOURCE_NAME, url=url,
                               attempt=attempt + 1, max=self.MAX_RETRIES)
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(5 * (attempt + 1))

            except Exception as e:
                error_str = str(e).lower()
                # 验证码检测
                if any(kw in error_str for kw in ["captcha", "blocked", "forbidden"]):
                    logger.warning("检测到验证码/封禁", source=self.SOURCE_NAME, url=url)
                    return None
                logger.error("Playwright异常", source=self.SOURCE_NAME,
                             url=url, error=str(e), attempt=attempt + 1)
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(3 * (attempt + 1))

            finally:
                # 强制关闭，防内存泄漏
                try:
                    if page:
                        await page.close()
                except Exception:
                    pass
                try:
                    if context:
                        await context.close()
                except Exception:
                    pass
                try:
                    if browser:
                        await browser.close()
                except Exception:
                    pass

        return None

    async def get_page_with_httpx(self, url: str) -> Optional[str]:
        """备用：httpx获取页面（比Playwright轻量）"""
        import httpx
        headers = {
            "User-Agent": self.get_random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code in (403, 429):
                        logger.warning("HTTP反爬", source=self.SOURCE_NAME, status=resp.status_code)
                        return None
                    if resp.status_code == 200:
                        return resp.text
                    return None
            except Exception as e:
                logger.warning("httpx请求失败", url=url, error=str(e), attempt=attempt + 1)
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 * (attempt + 1))
        return None

    def parse_buyers_from_html(self, html: str, source: str) -> list[dict]:
        """子类实现具体解析逻辑"""
        raise NotImplementedError

    def make_buyer(self, company_name: str = "", country: str = "",
                   website: str = "", email: str = "",
                   whatsapp: str = "", facebook: str = "",
                   linkedin: str = "", categories: list = None,
                   source: str = "") -> dict:
        """创建标准买家数据字典"""
        return {
            "company_name": company_name.strip()[:200],
            "country": country.strip()[:100],
            "website": website.strip()[:500],
            "email": email.strip().lower()[:200],
            "whatsapp": whatsapp.strip()[:50],
            "facebook": facebook.strip()[:500],
            "linkedin": linkedin.strip()[:500],
            "categories": categories or [],
            "source": source or self.SOURCE_NAME,
            "contact_status": "new",
            "email_status": "not_sent",
        }
