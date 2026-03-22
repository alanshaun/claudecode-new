"""
Alibaba International RFQ scraper (public pages)
URL: https://sourcing.alibaba.com/rfq/rfq_search_list.htm?searchText={keyword}
Uses Playwright (headless) to load dynamic content.
"""
import asyncio
import random
import re
import json
import structlog
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "alibaba_rfq"

PLAYWRIGHT_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--disable-background-networking",
]


def _make_buyer(company_name="", country="", website="", email="",
                whatsapp="", facebook="", linkedin="", categories=None):
    return {
        "company_name": company_name.strip()[:200],
        "country": country.strip()[:100],
        "website": website.strip()[:500],
        "email": email.strip().lower()[:200],
        "whatsapp": whatsapp.strip()[:50],
        "facebook": facebook.strip()[:500],
        "linkedin": linkedin.strip()[:500],
        "categories": categories or [],
        "source": SOURCE_NAME,
        "contact_status": "new",
        "email_status": "not_sent",
    }


def _parse_rfq_html(html: str, keyword: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # RFQ listing cards
        rfq_cards = (
            soup.select("div.rfq-list-item")
            or soup.select("div[class*='rfq-item']")
            or soup.select("div[class*='rfq_item']")
            or soup.select("li[class*='rfq']")
            or soup.select("div[class*='buyer']")
        )

        for card in rfq_cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Buyer/company name
                name_el = (
                    card.select_one("[class*='buyer-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("h3") or card.select_one("h2")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""

                # Country
                country_el = (
                    card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("[class*='flag']")
                )
                country = country_el.get_text(strip=True) if country_el else ""
                # Strip flag emoji if present
                country = re.sub(r"[^\x00-\x7F]+", "", country).strip()

                # Product/category
                product_el = (
                    card.select_one("[class*='product']")
                    or card.select_one("[class*='title']")
                    or card.select_one("h4")
                )
                product = product_el.get_text(strip=True) if product_el else keyword

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                if company_name or country:
                    buyers.append(_make_buyer(
                        company_name=company_name or "RFQ Buyer",
                        country=country,
                        email=email,
                        categories=[product, keyword] if product != keyword else [keyword],
                    ))
            except Exception as e:
                logger.warning("alibaba_rfq: card parse error", error=str(e))
                continue

        # Fallback: try JSON data in page scripts
        if not buyers:
            for script in soup.find_all("script"):
                script_text = script.string or ""
                if "rfq" in script_text.lower() and "buyer" in script_text.lower():
                    try:
                        match = re.search(r'window\.__INIT_DATA__\s*=\s*({.*?});', script_text, re.DOTALL)
                        if match:
                            data = json.loads(match.group(1))
                            rfq_list = data.get("rfqList") or data.get("list") or []
                            for item in rfq_list[:settings.MAX_RESULTS_PER_SOURCE]:
                                name = item.get("buyerName") or item.get("companyName") or ""
                                country = item.get("country") or item.get("buyerCountry") or ""
                                if name:
                                    buyers.append(_make_buyer(
                                        company_name=name,
                                        country=country,
                                        categories=[keyword],
                                    ))
                    except Exception:
                        continue

    except Exception as e:
        logger.error("alibaba_rfq: parse failed", error=str(e))

    return buyers


async def _fetch_with_playwright(url: str) -> str | None:
    for attempt in range(settings.SCRAPER_MAX_RETRIES):
        browser = context = page = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=settings.PLAYWRIGHT_HEADLESS,
                    args=PLAYWRIGHT_ARGS,
                )
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                page = await context.new_page()
                page.set_default_timeout(settings.PLAYWRIGHT_TIMEOUT)

                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))

                response = await page.goto(url, wait_until="domcontentloaded")
                if response and response.status in (403, 429):
                    logger.warning("alibaba_rfq: blocked", status=response.status)
                    return None

                # Wait for RFQ items to load
                try:
                    await page.wait_for_selector(
                        "div[class*='rfq'], div[class*='buyer'], li[class*='rfq']",
                        timeout=10000,
                    )
                except Exception:
                    pass  # Continue even if selector not found

                # Scroll to load lazy content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(1.5)

                html = await page.content()
                return html

        except asyncio.TimeoutError:
            logger.warning("alibaba_rfq: timeout", url=url, attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(5 * (attempt + 1))
        except Exception as e:
            logger.error("alibaba_rfq: playwright error", error=str(e), attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(3 * (attempt + 1))
        finally:
            for obj, method in [(page, "close"), (context, "close"), (browser, "close")]:
                if obj:
                    try:
                        await getattr(obj, method)()
                    except Exception:
                        pass

    return None


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    for keyword in keywords:
        url = f"https://sourcing.alibaba.com/rfq/rfq_search_list.htm?searchText={quote_plus(keyword)}"
        try:
            logger.info("alibaba_rfq: fetching", keyword=keyword)
            html = await _fetch_with_playwright(url)

            if html:
                buyers = _parse_rfq_html(html, keyword)
                for b in buyers:
                    key = (b["company_name"].lower(), b["country"].lower())
                    if key not in seen and b["company_name"]:
                        seen.add(key)
                        all_buyers.append(b)
                logger.info("alibaba_rfq: found buyers", keyword=keyword, count=len(buyers))
            else:
                logger.warning("alibaba_rfq: no HTML returned", keyword=keyword)

            await asyncio.sleep(random.uniform(2.0, 5.0))

        except Exception as e:
            logger.error("alibaba_rfq: unexpected error", keyword=keyword, error=str(e))

    logger.info("alibaba_rfq: scrape complete", total=len(all_buyers))
    return all_buyers
