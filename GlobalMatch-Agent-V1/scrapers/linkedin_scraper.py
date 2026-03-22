"""
LinkedIn public company page scraper (no login).
Strategy: Use Google to search "site:linkedin.com/company {keyword} importer",
then fetch LinkedIn public company pages for basic info.
Uses Playwright (headless). Only reads publicly visible info.
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

SOURCE_NAME = "linkedin"

PLAYWRIGHT_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--disable-background-networking",
]

LINKEDIN_COMPANY_BASE = "https://www.linkedin.com/company/"


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


def _extract_linkedin_urls_from_google(html: str) -> list[str]:
    """Extract linkedin.com/company URLs from Google search result HTML."""
    urls = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            # Google wraps links in /url?q=...
            match = re.search(r'(?:url\?q=|/url\?q=)(https?://(?:www\.)?linkedin\.com/company/[^&"]+)', href)
            if match:
                url = match.group(1)
                if url not in urls:
                    urls.append(url)
            # Also check direct LinkedIn links in cite/result text
            elif re.search(r'linkedin\.com/company/', href):
                clean = re.sub(r'\?.*$', '', href)
                if clean not in urls:
                    urls.append(clean)
    except Exception as e:
        logger.warning("linkedin: failed to extract URLs from Google HTML", error=str(e))
    return urls[:10]  # Cap at 10 LinkedIn URLs per query


def _parse_linkedin_public_page(html: str, url: str, keyword: str) -> dict | None:
    """Parse a LinkedIn public company page for basic info."""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Company name
        name_el = (
            soup.select_one("h1")
            or soup.select_one("[class*='org-top-card-summary__title']")
            or soup.select_one("[class*='top-card-layout__title']")
            or soup.select_one("title")
        )
        company_name = ""
        if name_el:
            raw = name_el.get_text(strip=True)
            # Strip " | LinkedIn" suffix from title tag
            company_name = re.sub(r"\s*\|\s*LinkedIn.*$", "", raw).strip()
        if not company_name:
            return None

        # Industry / category from meta description
        meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
        description = meta_desc.get("content", "") if meta_desc else ""

        # Location / country
        location_el = (
            soup.select_one("[class*='org-top-card-summary-info-list']")
            or soup.select_one("[class*='top-card-layout__first-subline']")
            or soup.select_one("[class*='company-industries']")
        )
        country = ""
        if location_el:
            location_text = location_el.get_text(strip=True)
            # Last part is usually location
            parts = [p.strip() for p in location_text.split("·") if p.strip()]
            if parts:
                country = parts[-1]

        # Extract company website from about section
        website_el = (
            soup.select_one("a[data-tracking-control-name*='website']")
            or soup.select_one("[class*='website'] a")
        )
        website = website_el.get("href", "") if website_el else ""
        if not website:
            # Try finding external link
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                if href.startswith("http") and "linkedin.com" not in href:
                    website = href
                    break

        # Email from page text
        page_text = soup.get_text()
        emails = extract_emails_from_text(page_text)
        email = emails[0] if emails else ""

        return _make_buyer(
            company_name=company_name,
            country=country,
            website=website,
            email=email,
            linkedin=url,
            categories=[keyword],
        )
    except Exception as e:
        logger.warning("linkedin: public page parse error", url=url, error=str(e))
        return None


async def _fetch_page(url: str) -> str | None:
    """Fetch a single page with Playwright."""
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
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                page = await context.new_page()
                page.set_default_timeout(settings.PLAYWRIGHT_TIMEOUT)

                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                response = await page.goto(url, wait_until="domcontentloaded")

                if response and response.status in (403, 429, 999):
                    logger.warning("linkedin: blocked/rate-limited", url=url, status=response.status)
                    return None

                # Check for login wall
                page_text = await page.inner_text("body")
                if "sign in" in page_text.lower() and "join linkedin" in page_text.lower():
                    # Login wall detected - extract what's visible in the HTML anyway
                    pass  # We'll still parse what we can

                await asyncio.sleep(random.uniform(1.0, 2.0))
                return await page.content()

        except asyncio.TimeoutError:
            logger.warning("linkedin: timeout", url=url, attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(5 * (attempt + 1))
        except Exception as e:
            logger.error("linkedin: playwright error", url=url, error=str(e), attempt=attempt + 1)
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

    for keyword in keywords:
        for country in (countries or [""]):
            # Step 1: Google search for LinkedIn company pages
            query_parts = [f"site:linkedin.com/company", keyword, "importer"]
            if country:
                query_parts.append(country)
            query = " ".join(query_parts)
            google_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&num=10"

            try:
                logger.info("linkedin: searching Google", query=query)
                google_html = await _fetch_page(google_url)

                if not google_html:
                    logger.warning("linkedin: no Google results", keyword=keyword)
                    continue

                linkedin_urls = _extract_linkedin_urls_from_google(google_html)
                logger.info("linkedin: found LinkedIn URLs", count=len(linkedin_urls))

                # Step 2: Fetch each LinkedIn public company page
                for li_url in linkedin_urls:
                    try:
                        # Normalize URL
                        if not li_url.startswith("http"):
                            li_url = "https://www.linkedin.com" + li_url
                        li_url = re.sub(r'\?.*$', '', li_url)  # remove query params

                        logger.info("linkedin: fetching company page", url=li_url)
                        page_html = await _fetch_page(li_url)

                        if page_html:
                            buyer = _parse_linkedin_public_page(page_html, li_url, keyword)
                            if buyer:
                                key = (buyer["company_name"].lower(), li_url.lower())
                                if key not in seen:
                                    seen.add(key)
                                    all_buyers.append(buyer)

                        # Longer delay between LinkedIn pages to avoid detection
                        await asyncio.sleep(random.uniform(3.0, 7.0))

                    except Exception as e:
                        logger.warning("linkedin: company page error", url=li_url, error=str(e))
                        continue

                # Delay between keyword searches
                await asyncio.sleep(random.uniform(8.0, 15.0))

            except Exception as e:
                logger.error("linkedin: unexpected error", keyword=keyword, error=str(e))

    logger.info("linkedin: scrape complete", total=len(all_buyers))
    return all_buyers
