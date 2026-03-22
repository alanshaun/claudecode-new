"""
Tradeindia.com scraper - India / Southeast Asia B2B directory.
URL: https://www.tradeindia.com/search.html?keyword={keyword}
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

SOURCE_NAME = "tradeindia"


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
        "Referer": "https://www.tradeindia.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_tradeindia_html(html: str, keyword: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Organization", "LocalBusiness"):
                        name = item.get("name", "")
                        if name:
                            addr = item.get("address") or {}
                            buyers.append(_make_buyer(
                                company_name=name,
                                country=addr.get("addressCountry", "India"),
                                website=item.get("url", ""),
                                email=item.get("email", ""),
                                categories=[keyword],
                            ))
            except Exception:
                continue

        # Company listing cards
        cards = (
            soup.select("div.companyBox")
            or soup.select("div[class*='company-box']")
            or soup.select("div[class*='company_box']")
            or soup.select("div.product-listing")
            or soup.select("li[class*='company']")
            or soup.select("div[class*='listing']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h3") or card.select_one("h2")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='companyName']")
                    or card.select_one("a.name")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Website
                link_el = card.select_one("a[href*='/Seller/']") or card.select_one("a[href]")
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = "https://www.tradeindia.com" + href

                # Location / city
                loc_el = (
                    card.select_one("[class*='location']")
                    or card.select_one("[class*='city']")
                    or card.select_one("[class*='address']")
                )
                location = loc_el.get_text(strip=True) if loc_el else ""
                country = "India"  # TradeIndia is India-based
                if location and any(c.isalpha() for c in location):
                    country = f"India ({location})" if location else "India"

                # Product categories
                cat_el = card.select_one("[class*='category']") or card.select_one("[class*='product']")
                categories = [cat_el.get_text(strip=True)] if cat_el else [keyword]

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                # WhatsApp number (Indian companies often list mobile)
                phone_el = card.select_one("[class*='phone']") or card.select_one("[class*='mobile']")
                whatsapp = ""
                if phone_el:
                    phone_text = phone_el.get_text(strip=True)
                    phone_clean = re.sub(r"[^\d\+]", "", phone_text)
                    if len(phone_clean) >= 10:
                        whatsapp = phone_clean

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=country,
                    website=website,
                    email=email,
                    whatsapp=whatsapp,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("tradeindia: card parse error", error=str(e))
                continue

    except Exception as e:
        logger.error("tradeindia: HTML parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            url = f"https://www.tradeindia.com/search.html?keyword={quote_plus(keyword)}"
            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("tradeindia: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    buyers = _parse_tradeindia_html(resp.text, keyword)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["website"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("tradeindia: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("tradeindia: rate limited", status=resp.status_code)
                    await asyncio.sleep(12)
                else:
                    logger.warning("tradeindia: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("tradeindia: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("tradeindia: request error", error=str(e))
            except Exception as e:
                logger.error("tradeindia: unexpected error", keyword=keyword, error=str(e))

    logger.info("tradeindia: scrape complete", total=len(all_buyers))
    return all_buyers
