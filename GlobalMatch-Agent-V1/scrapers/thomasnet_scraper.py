"""
Thomasnet.com scraper - US industrial buyers directory
URL: https://www.thomasnet.com/products/{keyword}/
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

SOURCE_NAME = "thomasnet"
BASE_URL = "https://www.thomasnet.com"


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
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_thomasnet_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Thomasnet company result cards - profile cards with supplier info
        cards = (
            soup.select("div.profile-card")
            or soup.select("div[class*='supplier-card']")
            or soup.select("div[class*='ProfileCard']")
            or soup.select("article[class*='profile']")
            or soup.select("div[data-component='ProfileCard']")
            or soup.select("div[class*='result']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h2[class*='name']")
                    or card.select_one("h2[class*='title']")
                    or card.select_one("a[class*='company-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Website / profile link
                link_el = card.select_one("a[href*='/company/']") or card.select_one("a[href]")
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
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Email extraction from card text
                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                # Categories / product tags
                cat_els = card.select("[class*='category']") or card.select("[class*='product-tag']")
                categories = [c.get_text(strip=True) for c in cat_els if c.get_text(strip=True)]
                if keyword not in categories:
                    categories.insert(0, keyword)

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("thomasnet: card parse error", error=str(e))
                continue

        # Fallback: parse any anchor with company-like text if no cards found
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
        logger.error("thomasnet: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    # Thomasnet is US-focused; skip if explicitly non-US countries only
    us_relevant = not countries or any(
        c.lower() in ("us", "usa", "united states", "") for c in countries
    )
    target_country = "United States"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            slug = quote_plus(keyword.lower().replace(" ", "-"))
            url = f"{BASE_URL}/products/{slug}/"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("thomasnet: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    buyers = _parse_thomasnet_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("thomasnet: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("thomasnet: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    # Try alternate URL pattern
                    alt_url = f"{BASE_URL}/products/{quote_plus(keyword)}/"
                    await asyncio.sleep(random.uniform(1, 2))
                    resp2 = await client.get(alt_url, headers=_get_headers())
                    if resp2.status_code == 200:
                        buyers = _parse_thomasnet_results(resp2.text, keyword, target_country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                else:
                    logger.warning("thomasnet: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("thomasnet: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("thomasnet: request error", error=str(e))
            except Exception as e:
                logger.error("thomasnet: unexpected error", error=str(e))

    logger.info("thomasnet: scrape complete", total=len(all_buyers))
    return all_buyers
