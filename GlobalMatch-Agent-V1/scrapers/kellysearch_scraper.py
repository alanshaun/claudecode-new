"""
Kellysearch.com scraper - UK industrial buyers directory
URL: https://www.kellysearch.com/gb-search.html?what={keyword}
Uses httpx + BeautifulSoup.
"""
import asyncio
import random
import re
import structlog
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "kellysearch"
BASE_URL = "https://www.kellysearch.com"


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


def _get_headers(referer: str = BASE_URL + "/") -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


# Map country filter codes for Kellysearch regions
COUNTRY_SLUGS = {
    "united kingdom": "gb",
    "uk": "gb",
    "ireland": "ie",
    "germany": "de",
    "france": "fr",
    "united states": "us",
    "usa": "us",
}


def _parse_kellysearch_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Kellysearch result entries
        cards = (
            soup.select("div.result-item")
            or soup.select("div[class*='ResultItem']")
            or soup.select("div[class*='company-listing']")
            or soup.select("li[class*='result']")
            or soup.select("div[class*='listing']")
            or soup.select("table.results tr[class*='result']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h2[class*='name']")
                    or card.select_one("h3[class*='name']")
                    or card.select_one("a[class*='company']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("a[href*='/gb-company']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Profile link / website
                link_el = (
                    card.select_one("a[href*='company']")
                    or card.select_one("a[class*='website']")
                    or card.select_one("a[href*='http']")
                    or card.select_one("a[href]")
                )
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = BASE_URL + href

                # Location
                loc_el = (
                    card.select_one("[class*='location']")
                    or card.select_one("[class*='address']")
                    or card.select_one("[class*='town']")
                    or card.select_one("[class*='postcode']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Categories / product descriptions
                desc_el = (
                    card.select_one("[class*='description']")
                    or card.select_one("[class*='product']")
                    or card.select_one("p")
                )
                description = desc_el.get_text(strip=True) if desc_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                categories = [keyword]
                if description and description != keyword:
                    # Use description words as secondary category hint
                    categories.append(description[:80])

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("kellysearch: card parse error", error=str(e))
                continue

        # Fallback: any company-profile anchors
        if not buyers:
            for anchor in soup.select("a[href*='/gb-company']")[:settings.MAX_RESULTS_PER_SOURCE]:
                try:
                    name = anchor.get_text(strip=True)
                    href = anchor.get("href", "")
                    if name and len(name) > 2:
                        website = href if href.startswith("http") else BASE_URL + href
                        buyers.append(_make_buyer(
                            company_name=name,
                            country=country,
                            website=website,
                            categories=[keyword],
                        ))
                except Exception:
                    continue

    except Exception as e:
        logger.error("kellysearch: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["United Kingdom"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            for country in countries:
                country_code = COUNTRY_SLUGS.get(country.lower().strip(), "gb")
                url = f"{BASE_URL}/{country_code}-search.html?what={quote_plus(keyword)}"

                try:
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    logger.info("kellysearch: fetching", url=url)

                    resp = await client.get(url, headers=_get_headers())

                    if resp.status_code == 200:
                        buyers = _parse_kellysearch_results(resp.text, keyword, country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                        logger.info("kellysearch: found buyers", keyword=keyword,
                                    country=country, count=len(buyers))
                    elif resp.status_code in (403, 429):
                        logger.warning("kellysearch: rate limited", status=resp.status_code)
                        await asyncio.sleep(20)
                    elif resp.status_code == 301:
                        logger.info("kellysearch: redirect received", url=url)
                    else:
                        logger.warning("kellysearch: unexpected status",
                                       status=resp.status_code, url=url)

                except httpx.TimeoutException:
                    logger.warning("kellysearch: timeout", url=url)
                except httpx.RequestError as e:
                    logger.error("kellysearch: request error", error=str(e))
                except Exception as e:
                    logger.error("kellysearch: unexpected error", error=str(e))

    logger.info("kellysearch: scrape complete", total=len(all_buyers))
    return all_buyers
