"""
Europages.com scraper - largest European B2B directory.
URL: https://www.europages.com/en/search?cserpRedirect=1&text={keyword}
Uses httpx + BeautifulSoup.
"""
import asyncio
import random
import json
import re
import structlog
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "europages"

# Europages country filter codes
COUNTRY_CODES = {
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES",
    "united kingdom": "GB", "uk": "GB", "netherlands": "NL",
    "belgium": "BE", "poland": "PL", "sweden": "SE", "austria": "AT",
    "switzerland": "CH", "portugal": "PT", "denmark": "DK",
    "norway": "NO", "finland": "FI", "czech republic": "CZ",
    "romania": "RO", "hungary": "HU", "greece": "GR",
    "turkey": "TR", "russia": "RU", "ukraine": "UA",
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


def _get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.europages.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_europages_html(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD structured data first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    org_type = item.get("@type", "")
                    if org_type in ("Organization", "LocalBusiness", "Corporation"):
                        name = item.get("name", "")
                        if name:
                            addr = item.get("address") or {}
                            detected_country = (
                                addr.get("addressCountry") or
                                addr.get("addressRegion") or
                                country
                            )
                            buyers.append(_make_buyer(
                                company_name=name,
                                country=detected_country,
                                website=item.get("url", ""),
                                email=item.get("email", ""),
                                categories=[keyword],
                            ))
            except Exception:
                continue

        # Parse company cards from HTML
        cards = (
            soup.select("div.company-card")
            or soup.select("article[class*='company']")
            or soup.select("div[class*='result']")
            or soup.select("li[class*='company']")
            or soup.select("div[data-company-id]")
            or soup.select("div[class*='ep-card']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                name_el = (
                    card.select_one("h2") or card.select_one("h3")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='name']")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Website link
                link_el = card.select_one("a[href*='/company/'], a[href*='/en/']")
                if not link_el:
                    link_el = card.select_one("a[href]")
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = "https://www.europages.com" + href

                # Country
                country_el = (
                    card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("[class*='flag']")
                )
                detected_country = country_el.get_text(strip=True) if country_el else country
                # Strip flag emoji
                detected_country = re.sub(r"[^\x00-\x7F]+", "", detected_country).strip() or country

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=[keyword],
                ))
            except Exception as e:
                logger.warning("europages: card parse error", error=str(e))
                continue

    except Exception as e:
        logger.error("europages: HTML parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    target_countries = countries if countries else [""]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            for country in target_countries:
                country_code = COUNTRY_CODES.get(country.lower().strip(), "")
                params = f"cserpRedirect=1&text={quote_plus(keyword)}"
                if country_code:
                    params += f"&countryCode={country_code}"
                url = f"https://www.europages.com/en/search?{params}"

                try:
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    logger.info("europages: fetching", url=url)

                    resp = await client.get(url, headers=_get_headers())

                    if resp.status_code == 200:
                        buyers = _parse_europages_html(resp.text, keyword, country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                        logger.info("europages: found buyers", keyword=keyword, country=country, count=len(buyers))
                    elif resp.status_code in (403, 429):
                        logger.warning("europages: rate limited", status=resp.status_code)
                        await asyncio.sleep(15)
                    else:
                        logger.warning("europages: unexpected status", status=resp.status_code, url=url)

                except httpx.TimeoutException:
                    logger.warning("europages: timeout", url=url)
                except httpx.RequestError as e:
                    logger.error("europages: request error", error=str(e))
                except Exception as e:
                    logger.error("europages: unexpected error", keyword=keyword, error=str(e))

    logger.info("europages: scrape complete", total=len(all_buyers))
    return all_buyers
