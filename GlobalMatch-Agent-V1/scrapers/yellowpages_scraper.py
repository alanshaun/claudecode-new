"""
YellowPages.com scraper (US) - business directory.
URL: https://www.yellowpages.com/search?search_terms={keyword}&geo_location_terms={location}
Uses httpx + BeautifulSoup.
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

SOURCE_NAME = "yellowpages"

# Map country names to US geo locations for YP (US-centric)
US_GEO_MAP = {
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "new york": "New York, NY",
    "los angeles": "Los Angeles, CA",
    "chicago": "Chicago, IL",
    "houston": "Houston, TX",
    "miami": "Miami, FL",
}


def _make_buyer(company_name="", country="", website="", email="",
                whatsapp="", facebook="", linkedin="", categories=None,
                phone=""):
    return {
        "company_name": company_name.strip()[:200],
        "country": country.strip()[:100],
        "website": website.strip()[:500],
        "email": email.strip().lower()[:200],
        "whatsapp": phone.strip()[:50] if phone else whatsapp.strip()[:50],
        "facebook": facebook.strip()[:500],
        "linkedin": linkedin.strip()[:500],
        "categories": categories or [],
        "source": SOURCE_NAME,
        "contact_status": "new",
        "email_status": "not_sent",
    }


def _get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.yellowpages.com/",
        "Connection": "keep-alive",
    }


def _parse_yellowpages_html(html: str, keyword: str, geo: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # YP listing results
        listings = (
            soup.select("div.result")
            or soup.select("div[class*='result']")
            or soup.select("article[class*='listing']")
            or soup.select("div.v-card")
            or soup.select("div[class*='business']")
        )

        for listing in listings[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    listing.select_one("a.business-name")
                    or listing.select_one("h2.n") or listing.select_one("h2")
                    or listing.select_one("[class*='business-name']")
                    or listing.select_one("strong.business-name")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Website
                website_el = (
                    listing.select_one("a[class*='track-visit-website']")
                    or listing.select_one("a[href*='yellowpages.com/url']")
                    or listing.select_one("a.website-link")
                )
                website = ""
                if website_el:
                    href = website_el.get("href", "")
                    # YP often uses redirect URLs, extract the real URL
                    match = re.search(r'url=([^&]+)', href)
                    if match:
                        from urllib.parse import unquote
                        website = unquote(match.group(1))
                    elif href.startswith("http"):
                        website = href

                # Phone (stored in whatsapp field as contact number)
                phone_el = (
                    listing.select_one("div.phones") or listing.select_one("[class*='phone']")
                )
                phone = phone_el.get_text(strip=True) if phone_el else ""
                phone = re.sub(r"[^\d\s\-\+\(\)]", "", phone).strip()

                # Categories
                category_el = listing.select_one("div.categories") or listing.select_one("[class*='categories']")
                categories = []
                if category_el:
                    for a in category_el.select("a"):
                        cat = a.get_text(strip=True)
                        if cat:
                            categories.append(cat)
                if not categories:
                    categories = [keyword]

                # Address / location
                addr_el = listing.select_one("div.adr") or listing.select_one("[class*='address']")
                addr_text = addr_el.get_text(strip=True) if addr_el else ""

                listing_text = listing.get_text()
                emails = extract_emails_from_text(listing_text)
                email = emails[0] if emails else ""

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country="United States",
                    website=website,
                    email=email,
                    phone=phone,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("yellowpages: listing parse error", error=str(e))
                continue

        # JSON-LD fallback
        if not buyers:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") in ("LocalBusiness", "Organization"):
                            name = item.get("name", "")
                            if name:
                                buyers.append(_make_buyer(
                                    company_name=name,
                                    country="United States",
                                    website=item.get("url", ""),
                                    email=item.get("email", ""),
                                    phone=item.get("telephone", ""),
                                    categories=[keyword],
                                ))
                except Exception:
                    continue

    except Exception as e:
        logger.error("yellowpages: HTML parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    # YellowPages is US-only; map requested countries to geo strings
    geo_locations = []
    for c in (countries or ["United States"]):
        geo = US_GEO_MAP.get(c.lower().strip(), c if c else "United States")
        geo_locations.append(geo)
    if not geo_locations:
        geo_locations = ["United States"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            for geo in geo_locations:
                url = (
                    f"https://www.yellowpages.com/search"
                    f"?search_terms={quote_plus(keyword)}"
                    f"&geo_location_terms={quote_plus(geo)}"
                )
                try:
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    logger.info("yellowpages: fetching", url=url)

                    resp = await client.get(url, headers=_get_headers())

                    if resp.status_code == 200:
                        buyers = _parse_yellowpages_html(resp.text, keyword, geo)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["website"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                        logger.info("yellowpages: found buyers", keyword=keyword, geo=geo, count=len(buyers))
                    elif resp.status_code in (403, 429):
                        logger.warning("yellowpages: rate limited", status=resp.status_code)
                        await asyncio.sleep(10)
                    else:
                        logger.warning("yellowpages: unexpected status", status=resp.status_code, url=url)

                except httpx.TimeoutException:
                    logger.warning("yellowpages: timeout", url=url)
                except httpx.RequestError as e:
                    logger.error("yellowpages: request error", error=str(e))
                except Exception as e:
                    logger.error("yellowpages: unexpected error", keyword=keyword, error=str(e))

    logger.info("yellowpages: scrape complete", total=len(all_buyers))
    return all_buyers
