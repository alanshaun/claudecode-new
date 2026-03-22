"""
ImportYeti.com scraper - US importers data
Public search results, no login required.
URL pattern: https://www.importyeti.com/search?query={keyword}
"""
import asyncio
import random
import re
import structlog
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from config import USER_AGENTS, settings
from utils.email_validator import extract_emails_from_text

logger = structlog.get_logger(__name__)

SOURCE_NAME = "importyeti"


def _make_buyer(company_name="", country="", website="", email="",
                whatsapp="", facebook="", linkedin="", categories=None, source=SOURCE_NAME):
    return {
        "company_name": company_name.strip()[:200],
        "country": country.strip()[:100],
        "website": website.strip()[:500],
        "email": email.strip().lower()[:200],
        "whatsapp": whatsapp.strip()[:50],
        "facebook": facebook.strip()[:500],
        "linkedin": linkedin.strip()[:500],
        "categories": categories or [],
        "source": source,
        "contact_status": "new",
        "email_status": "not_sent",
    }


def _get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.importyeti.com/",
    }


def _parse_search_results(html: str, keyword: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # ImportYeti renders company cards - look for common selectors
        company_cards = (
            soup.select("div.company-card")
            or soup.select("div[class*='company']")
            or soup.select("a[href*='/company/']")
        )

        for card in company_cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("[class*='name']")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""

                # If card is an anchor tag itself
                if not company_name and card.name == "a":
                    company_name = card.get_text(strip=True)

                if not company_name:
                    continue

                # Website / profile link
                link = card.get("href", "") if card.name == "a" else ""
                if not link:
                    a_tag = card.select_one("a[href*='/company/']")
                    link = a_tag.get("href", "") if a_tag else ""
                if link and link.startswith("/"):
                    link = "https://www.importyeti.com" + link

                # Country - US importers are mostly USA
                country_el = card.select_one("[class*='country']") or card.select_one("[class*='location']")
                country = country_el.get_text(strip=True) if country_el else "United States"

                # Extract emails from card text
                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                buyer = _make_buyer(
                    company_name=company_name,
                    country=country,
                    website=link,
                    email=email,
                    categories=[keyword],
                )
                buyers.append(buyer)

            except Exception as e:
                logger.warning("importyeti: failed parsing card", error=str(e))
                continue

        # Fallback: parse any structured data in JSON-LD or script tags
        if not buyers:
            scripts = soup.find_all("script", type="application/json")
            for script in scripts:
                try:
                    import json
                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        for item in data[:settings.MAX_RESULTS_PER_SOURCE]:
                            name = item.get("name") or item.get("company_name") or ""
                            if name:
                                buyers.append(_make_buyer(
                                    company_name=name,
                                    country=item.get("country", "United States"),
                                    website=item.get("website", ""),
                                    email=item.get("email", ""),
                                    categories=[keyword],
                                ))
                except Exception:
                    continue

    except Exception as e:
        logger.error("importyeti: HTML parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers=_get_headers(),
    ) as client:
        for keyword in keywords:
            url = f"https://www.importyeti.com/search?query={quote_plus(keyword)}"
            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("importyeti: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    buyers = _parse_search_results(resp.text, keyword)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("importyeti: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("importyeti: rate limited or blocked", status=resp.status_code)
                    await asyncio.sleep(10)
                else:
                    logger.warning("importyeti: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("importyeti: request timed out", url=url)
            except httpx.RequestError as e:
                logger.error("importyeti: request error", url=url, error=str(e))
            except Exception as e:
                logger.error("importyeti: unexpected error", url=url, error=str(e))

    logger.info("importyeti: scrape complete", total=len(all_buyers))
    return all_buyers
