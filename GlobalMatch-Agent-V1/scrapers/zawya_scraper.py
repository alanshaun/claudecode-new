"""
Zawya.com scraper - Middle East & Africa business intelligence
URL: https://www.zawya.com/en/companies/search?q={keyword}
Uses httpx + BeautifulSoup.
"""
import asyncio
import random
import json
import re
import structlog
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "zawya"
BASE_URL = "https://www.zawya.com"

# Zawya covers these Middle East / Africa / South Asia countries
MENA_COUNTRIES = {
    "uae", "united arab emirates", "saudi arabia", "ksa", "egypt",
    "qatar", "kuwait", "bahrain", "oman", "jordan", "lebanon",
    "iraq", "iran", "morocco", "algeria", "tunisia", "libya",
    "pakistan", "bangladesh",
}


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
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


def _parse_zawya_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD structured data first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    # Handle @graph arrays
                    if "@graph" in item:
                        items = item["@graph"]
                        break
                for item in items:
                    if item.get("@type") in ("Organization", "Corporation", "LocalBusiness"):
                        name = item.get("name", "")
                        if name:
                            buyers.append(_make_buyer(
                                company_name=name,
                                country=item.get("addressCountry") or country,
                                website=item.get("url", ""),
                                email=item.get("email", ""),
                                categories=[keyword],
                            ))
            except Exception:
                continue

        # Zawya company search result cards
        cards = (
            soup.select("div[class*='CompanyCard']")
            or soup.select("div[class*='company-card']")
            or soup.select("article[class*='company']")
            or soup.select("div[class*='search-result']")
            or soup.select("li[class*='company']")
            or soup.select("div[class*='result-item']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                name_el = (
                    card.select_one("[class*='company-name']")
                    or card.select_one("[class*='CompanyName']")
                    or card.select_one("h2[class*='title']")
                    or card.select_one("h3[class*='title']")
                    or card.select_one("a[class*='name']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Profile link
                link_el = (
                    card.select_one("a[href*='/en/companies/']")
                    or card.select_one("a[href*='/company/']")
                    or card.select_one("a[href]")
                )
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = BASE_URL + href

                # Country / location
                loc_el = (
                    card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("[class*='address']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Industry / sector
                sector_el = (
                    card.select_one("[class*='sector']")
                    or card.select_one("[class*='industry']")
                    or card.select_one("[class*='category']")
                )
                sector = sector_el.get_text(strip=True) if sector_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                categories = [keyword]
                if sector and sector != keyword:
                    categories.append(sector)

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("zawya: card parse error", error=str(e))
                continue

        # Fallback: company profile links
        if not buyers:
            for anchor in soup.select("a[href*='/en/companies/']")[:settings.MAX_RESULTS_PER_SOURCE]:
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
        logger.error("zawya: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["UAE"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            url = f"{BASE_URL}/en/companies/search?q={quote_plus(keyword)}"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("zawya: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "UAE"
                    buyers = _parse_zawya_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("zawya: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("zawya: rate limited / blocked", status=resp.status_code)
                    await asyncio.sleep(25)
                elif resp.status_code == 404:
                    logger.info("zawya: no results found", keyword=keyword)
                else:
                    logger.warning("zawya: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("zawya: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("zawya: request error", error=str(e))
            except Exception as e:
                logger.error("zawya: unexpected error", error=str(e))

    logger.info("zawya: scrape complete", total=len(all_buyers))
    return all_buyers
