"""
Piers.com scraper - US customs / trade data (public pages).
URL: https://www.piers.com/search?query={keyword}
Uses httpx + BeautifulSoup. Extracts importer names and contact info
from publicly accessible search result pages.
"""
import asyncio
import random
import re
import json
import structlog
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "piers"

# Piers is US-focused customs data; complement with PIERS partner pages
PIERS_BASE = "https://www.piers.com"
FALLBACK_SOURCES = [
    "https://www.importgenius.com/search?q={keyword}",
    "https://www.trademo.com/search?keyword={keyword}",
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


def _get_headers(referer: str = PIERS_BASE):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer + "/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_piers_html(html: str, keyword: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Organization", "Corporation"):
                        name = item.get("name", "")
                        if name:
                            buyers.append(_make_buyer(
                                company_name=name,
                                country=item.get("addressCountry", "United States"),
                                website=item.get("url", ""),
                                email=item.get("email", ""),
                                categories=[keyword],
                            ))
            except Exception:
                continue

        # Company / importer result cards
        cards = (
            soup.select("div.company-result")
            or soup.select("div[class*='importer']")
            or soup.select("div[class*='shipper']")
            or soup.select("tr[class*='result']")
            or soup.select("div[class*='result-item']")
            or soup.select("div[class*='search-result']")
            or soup.select("li[class*='result']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                name_el = (
                    card.select_one("[class*='company-name']")
                    or card.select_one("[class*='importer-name']")
                    or card.select_one("h2") or card.select_one("h3")
                    or card.select_one("strong") or card.select_one("td:first-child")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Link
                link_el = card.select_one("a[href]")
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = PIERS_BASE + href

                # Country / address
                addr_el = (
                    card.select_one("[class*='address']")
                    or card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                )
                country = addr_el.get_text(strip=True) if addr_el else "United States"
                if not country:
                    country = "United States"

                # Shipment count or value (context info)
                shipment_el = card.select_one("[class*='shipment']") or card.select_one("[class*='volume']")
                extra_info = shipment_el.get_text(strip=True) if shipment_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=country,
                    website=website,
                    email=email,
                    categories=[keyword],
                ))
            except Exception as e:
                logger.warning("piers: card parse error", error=str(e))
                continue

        # Table-based results (some pages use tables)
        if not buyers:
            tables = soup.select("table[class*='result'], table[class*='importer']")
            for table in tables:
                for row in table.select("tr")[1:settings.MAX_RESULTS_PER_SOURCE + 1]:
                    try:
                        cells = row.select("td")
                        if len(cells) >= 2:
                            company_name = cells[0].get_text(strip=True)
                            country = cells[1].get_text(strip=True) if len(cells) > 1 else "United States"
                            if company_name:
                                buyers.append(_make_buyer(
                                    company_name=company_name,
                                    country=country,
                                    categories=[keyword],
                                ))
                    except Exception:
                        continue

    except Exception as e:
        logger.error("piers: HTML parse failed", error=str(e))

    return buyers


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch URL with retries."""
    for attempt in range(settings.SCRAPER_MAX_RETRIES):
        try:
            resp = await client.get(url, headers=_get_headers())
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                logger.warning("piers: rate limited", status=resp.status_code, url=url)
                await asyncio.sleep(10 * (attempt + 1))
                return None
            logger.warning("piers: unexpected status", status=resp.status_code, url=url)
            return None
        except httpx.TimeoutException:
            logger.warning("piers: timeout", url=url, attempt=attempt + 1)
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(3 * (attempt + 1))
        except httpx.RequestError as e:
            logger.error("piers: request error", url=url, error=str(e))
            if attempt < settings.SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:
            logger.error("piers: unexpected fetch error", url=url, error=str(e))
            return None

    return None


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            url = f"{PIERS_BASE}/search?query={quote_plus(keyword)}"
            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("piers: fetching", url=url)

                html = await _fetch(client, url)
                if html:
                    buyers = _parse_piers_html(html, keyword)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("piers: found buyers", keyword=keyword, count=len(buyers))
                else:
                    logger.warning("piers: no HTML returned", keyword=keyword)

            except Exception as e:
                logger.error("piers: unexpected error", keyword=keyword, error=str(e))

    logger.info("piers: scrape complete", total=len(all_buyers))
    return all_buyers
