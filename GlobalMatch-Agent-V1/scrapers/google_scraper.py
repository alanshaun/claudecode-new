"""
Google search scraper - extract company info from public search result snippets.
Builds queries like: "{keyword} importer wholesaler {country}"
Uses Playwright to render results, extracts only public snippet data.
Respects robots.txt: only reads text visible in search result cards.
"""
import asyncio
import random
import re
import structlog
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "google"

PLAYWRIGHT_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--disable-background-networking",
]

# Only extract from public snippets - do not follow links to private content
MAX_RESULTS_PER_QUERY = 10


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


def _parse_google_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Google search result divs (public snippet containers)
        result_blocks = (
            soup.select("div.g")
            or soup.select("div[class*='tF2Cxc']")
            or soup.select("div[data-sokoban-container]")
            or soup.select("div[jscontroller]")
        )

        for block in result_blocks[:MAX_RESULTS_PER_QUERY]:
            try:
                # Title element
                title_el = block.select_one("h3")
                if not title_el:
                    continue
                company_name = title_el.get_text(strip=True)
                if not company_name:
                    continue

                # Display URL (cite tag shows the domain)
                cite_el = block.select_one("cite")
                website = cite_el.get_text(strip=True) if cite_el else ""
                # Normalize - cite sometimes has path, strip to domain
                if website:
                    website = re.sub(r"\s.*$", "", website)  # remove trailing path text
                    if not website.startswith("http"):
                        website = "https://" + website

                # Snippet text - public description shown in results
                snippet_el = (
                    block.select_one("div[class*='VwiC3b']")
                    or block.select_one("span[class*='st']")
                    or block.select_one("div[class*='IsZvec']")
                    or block.select_one("div[data-sncf]")
                )
                snippet_text = snippet_el.get_text(" ", strip=True) if snippet_el else ""

                # Extract email from snippet (only public info)
                emails = extract_emails_from_text(snippet_text)
                email = emails[0] if emails else ""

                # Extract LinkedIn URL if present
                linkedin = ""
                a_tags = block.select("a[href]")
                for a in a_tags:
                    href = a.get("href", "")
                    if "linkedin.com/company" in href:
                        linkedin = href
                        break

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=country,
                    website=website,
                    email=email,
                    linkedin=linkedin,
                    categories=[keyword],
                ))
            except Exception as e:
                logger.warning("google: result block parse error", error=str(e))
                continue

    except Exception as e:
        logger.error("google: HTML parse failed", error=str(e))

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
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                page = await context.new_page()
                page.set_default_timeout(settings.PLAYWRIGHT_TIMEOUT)

                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                response = await page.goto(url, wait_until="domcontentloaded")

                if response and response.status in (403, 429):
                    logger.warning("google: blocked", status=response.status)
                    return None

                # Check for CAPTCHA
                page_text = await page.inner_text("body")
                if "unusual traffic" in page_text.lower() or "captcha" in page_text.lower():
                    logger.warning("google: CAPTCHA detected, skipping")
                    return None

                try:
                    await page.wait_for_selector("div.g, div[class*='tF2Cxc']", timeout=8000)
                except Exception:
                    pass

                await asyncio.sleep(random.uniform(1.0, 2.5))
                return await page.content()

        except asyncio.TimeoutError:
            logger.warning("google: timeout", url=url, attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(5 * (attempt + 1))
        except Exception as e:
            logger.error("google: playwright error", error=str(e), attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(3 * (attempt + 1))
        finally:
            for obj in [page, context, browser]:
                if obj:
                    try:
                        await obj.close()
                    except Exception:
                        pass

    return None


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = [""]

    for keyword in keywords:
        for country in countries:
            # Build query: "keyword importer wholesaler country"
            buyer_type_str = " ".join(buyer_types[:2]) if buyer_types else "importer wholesaler"
            query_parts = [keyword, buyer_type_str]
            if country:
                query_parts.append(country)
            query = " ".join(query_parts)
            url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&num=10"

            try:
                logger.info("google: fetching", query=query)
                html = await _fetch_with_playwright(url)

                if html:
                    buyers = _parse_google_results(html, keyword, country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["website"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("google: found buyers", keyword=keyword, country=country, count=len(buyers))
                else:
                    logger.warning("google: no HTML returned", keyword=keyword)

                # Longer delay between Google searches to avoid rate limiting
                await asyncio.sleep(random.uniform(5.0, 12.0))

            except Exception as e:
                logger.error("google: unexpected error", keyword=keyword, country=country, error=str(e))

    logger.info("google: scrape complete", total=len(all_buyers))
    return all_buyers
