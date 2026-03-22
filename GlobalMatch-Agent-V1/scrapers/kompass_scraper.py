"""
Kompass.com scraper - Global business directory
URL: https://us.kompass.com/searchCompanies?text={keyword}&country={country}
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

SOURCE_NAME = "kompass"

# Kompass country code mapping for common targets
COUNTRY_CODES = {
    "united states": "us", "usa": "us", "us": "us",
    "united kingdom": "gb", "uk": "gb",
    "germany": "de", "france": "fr", "italy": "it",
    "spain": "es", "netherlands": "nl", "belgium": "be",
    "brazil": "br", "india": "in", "china": "cn",
    "japan": "jp", "australia": "au", "canada": "ca",
    "mexico": "mx", "south korea": "kr", "turkey": "tr",
    "poland": "pl", "sweden": "se", "switzerland": "ch",
    "austria": "at", "portugal": "pt", "denmark": "dk",
    "norway": "no", "finland": "fi", "russia": "ru",
    "uae": "ae", "saudi arabia": "sa", "south africa": "za",
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


def _get_headers(referer: str = "https://us.kompass.com/"):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
    }


def _resolve_country_code(country: str) -> str:
    return COUNTRY_CODES.get(country.lower().strip(), "")


def _parse_kompass_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Try JSON-LD first
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else data.get("@graph", [data])
                for item in items:
                    if item.get("@type") in ("Organization", "LocalBusiness", "Corporation"):
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

        # Parse company listing cards
        cards = (
            soup.select("div.company-card")
            or soup.select("div[class*='result-item']")
            or soup.select("article[class*='company']")
            or soup.select("li[class*='company']")
            or soup.select("div[class*='card']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                name_el = (
                    card.select_one("h2") or card.select_one("h3")
                    or card.select_one("[class*='name']")
                    or card.select_one("[class*='title']")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                link_el = card.select_one("a[href]")
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = "https://us.kompass.com" + href

                country_el = card.select_one("[class*='country']") or card.select_one("[class*='location']")
                detected_country = country_el.get_text(strip=True) if country_el else country

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
                logger.warning("kompass: card parse error", error=str(e))
                continue

    except Exception as e:
        logger.error("kompass: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["United States"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            for country in countries:
                country_code = _resolve_country_code(country)
                params = f"text={quote_plus(keyword)}"
                if country_code:
                    params += f"&country={country_code}"
                url = f"https://us.kompass.com/searchCompanies?{params}"

                try:
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    logger.info("kompass: fetching", url=url)

                    resp = await client.get(url, headers=_get_headers())

                    if resp.status_code == 200:
                        buyers = _parse_kompass_results(resp.text, keyword, country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                        logger.info("kompass: found buyers", keyword=keyword, country=country, count=len(buyers))
                    elif resp.status_code in (403, 429):
                        logger.warning("kompass: rate limited", status=resp.status_code)
                        await asyncio.sleep(15)
                    else:
                        logger.warning("kompass: unexpected status", status=resp.status_code)

                except httpx.TimeoutException:
                    logger.warning("kompass: timeout", url=url)
                except httpx.RequestError as e:
                    logger.error("kompass: request error", error=str(e))
                except Exception as e:
                    logger.error("kompass: unexpected error", error=str(e))

    logger.info("kompass: scrape complete", total=len(all_buyers))
    return all_buyers
