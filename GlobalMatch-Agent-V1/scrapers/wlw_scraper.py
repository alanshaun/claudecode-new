"""
Wlw.de scraper - German industrial buyers directory (Wer liefert was)
URL: https://www.wlw.de/en/find/{keyword}
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

SOURCE_NAME = "wlw"
BASE_URL = "https://www.wlw.de"


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
        "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_wlw_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # WLW company result cards
        cards = (
            soup.select("div[class*='CompanyCard']")
            or soup.select("div[class*='company-card']")
            or soup.select("article[class*='company']")
            or soup.select("li[class*='supplier']")
            or soup.select("div[class*='result-item']")
            or soup.select("div[data-testid*='company']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h2[class*='name']")
                    or card.select_one("h3[class*='name']")
                    or card.select_one("[class*='CompanyName']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("a[class*='name']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Profile/website link
                link_el = (
                    card.select_one("a[href*='/en/']")
                    or card.select_one("a[href*='/de/']")
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

                # Location
                loc_el = (
                    card.select_one("[class*='location']")
                    or card.select_one("[class*='address']")
                    or card.select_one("[class*='city']")
                    or card.select_one("[class*='Location']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Product / category tags
                cat_els = (
                    card.select("[class*='product']")
                    or card.select("[class*='category']")
                    or card.select("[class*='tag']")
                )
                categories = [c.get_text(strip=True) for c in cat_els if c.get_text(strip=True)]
                if keyword not in categories:
                    categories.insert(0, keyword)

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("wlw: card parse error", error=str(e))
                continue

        # Fallback: anchor tags pointing to company profiles
        if not buyers:
            for anchor in soup.select("a[href*='/en/find/']")[:settings.MAX_RESULTS_PER_SOURCE]:
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
        logger.error("wlw: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    # WLW is primarily DACH (Germany, Austria, Switzerland)
    if not countries:
        countries = ["Germany"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            slug = keyword.lower().replace(" ", "-")
            url = f"{BASE_URL}/en/find/{quote_plus(slug)}"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("wlw: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "Germany"
                    buyers = _parse_wlw_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("wlw: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("wlw: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    # Try with spaces encoded as +
                    alt_url = f"{BASE_URL}/en/find/{quote_plus(keyword)}"
                    await asyncio.sleep(random.uniform(1, 2))
                    resp2 = await client.get(alt_url, headers=_get_headers())
                    if resp2.status_code == 200:
                        target_country = countries[0] if countries else "Germany"
                        buyers = _parse_wlw_results(resp2.text, keyword, target_country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                else:
                    logger.warning("wlw: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("wlw: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("wlw: request error", error=str(e))
            except Exception as e:
                logger.error("wlw: unexpected error", error=str(e))

    logger.info("wlw: scrape complete", total=len(all_buyers))
    return all_buyers
