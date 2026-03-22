"""
Hoovers.com scraper - Dun & Bradstreet public company pages
URL: https://www.hoovers.com/search.html?term={keyword}
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

SOURCE_NAME = "hoovers"
BASE_URL = "https://www.hoovers.com"


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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


def _parse_hoovers_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Hoovers search results - company rows/cards
        cards = (
            soup.select("div.company-result")
            or soup.select("div[class*='search-result']")
            or soup.select("tr[class*='company']")
            or soup.select("div[class*='CompanyCard']")
            or soup.select("li[class*='result-item']")
            or soup.select("div[class*='result-item']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name - usually in a prominent heading or link
                name_el = (
                    card.select_one("a[class*='company-name']")
                    or card.select_one("span[class*='company-name']")
                    or card.select_one("h2[class*='name']")
                    or card.select_one("h3[class*='name']")
                    or card.select_one("a[href*='/company/']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Website link
                link_el = (
                    card.select_one("a[class*='website']")
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

                # Location / country
                loc_el = (
                    card.select_one("[class*='location']")
                    or card.select_one("[class*='address']")
                    or card.select_one("[class*='country']")
                    or card.select_one("[class*='city']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Industry / SIC
                ind_el = (
                    card.select_one("[class*='industry']")
                    or card.select_one("[class*='sector']")
                    or card.select_one("[class*='sic']")
                )
                industry = ind_el.get_text(strip=True) if ind_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                categories = [keyword]
                if industry and industry != keyword:
                    categories.append(industry)

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("hoovers: card parse error", error=str(e))
                continue

        # Fallback: parse table rows for company links
        if not buyers:
            for anchor in soup.select("a[href*='/company/']")[:settings.MAX_RESULTS_PER_SOURCE]:
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
        logger.error("hoovers: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["United States"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            for country in countries:
                url = f"{BASE_URL}/search.html?term={quote_plus(keyword)}"

                try:
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    logger.info("hoovers: fetching", url=url)

                    resp = await client.get(url, headers=_get_headers())

                    if resp.status_code == 200:
                        buyers = _parse_hoovers_results(resp.text, keyword, country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                        logger.info("hoovers: found buyers", keyword=keyword, country=country, count=len(buyers))
                    elif resp.status_code in (403, 429):
                        logger.warning("hoovers: rate limited / blocked", status=resp.status_code)
                        await asyncio.sleep(20)
                    elif resp.status_code == 301:
                        logger.info("hoovers: redirect, skipping", url=url)
                    else:
                        logger.warning("hoovers: unexpected status", status=resp.status_code, url=url)

                except httpx.TimeoutException:
                    logger.warning("hoovers: timeout", url=url)
                except httpx.RequestError as e:
                    logger.error("hoovers: request error", error=str(e))
                except Exception as e:
                    logger.error("hoovers: unexpected error", error=str(e))

    logger.info("hoovers: scrape complete", total=len(all_buyers))
    return all_buyers
