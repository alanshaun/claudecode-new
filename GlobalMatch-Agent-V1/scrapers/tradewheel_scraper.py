"""
TradeWheel.com scraper - Global buyer inquiries / buy-offer listings
URL: https://www.tradewheel.com/buy-offers/{keyword}/
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

SOURCE_NAME = "tradewheel"
BASE_URL = "https://www.tradewheel.com"


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


def _keyword_to_slug(keyword: str) -> str:
    """Convert keyword to TradeWheel URL slug (hyphen-separated, lowercase)."""
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower().strip()).strip("-")


def _parse_tradewheel_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # TradeWheel buy-offer listing cards
        cards = (
            soup.select("div[class*='buy-offer']")
            or soup.select("div[class*='BuyOffer']")
            or soup.select("div[class*='offer-card']")
            or soup.select("li[class*='offer']")
            or soup.select("div[class*='inquiry']")
            or soup.select("div[class*='product-item']")
            or soup.select("article[class*='offer']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Buyer / company name - often the poster name on buy offers
                name_el = (
                    card.select_one("[class*='buyer-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='poster']")
                    or card.select_one("a[class*='company']")
                    or card.select_one("h2[class*='title']")
                    or card.select_one("h3[class*='title']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Profile or offer link
                link_el = (
                    card.select_one("a[href*='/company/']")
                    or card.select_one("a[href*='/buy-offer/']")
                    or card.select_one("a[href*='/buyer/']")
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
                country_el = (
                    card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("span[class*='flag']")
                    or card.select_one("[class*='member-country']")
                )
                detected_country = ""
                if country_el:
                    detected_country = country_el.get("title", "") or country_el.get_text(strip=True)
                if not detected_country:
                    detected_country = country

                # Quantity required / product requirement description
                qty_el = (
                    card.select_one("[class*='quantity']")
                    or card.select_one("[class*='requirement']")
                    or card.select_one("[class*='description']")
                    or card.select_one("p")
                )
                description = qty_el.get_text(strip=True) if qty_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                categories = [keyword]
                if description and len(description) > 3 and description != keyword:
                    categories.append(description[:80])

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("tradewheel: card parse error", error=str(e))
                continue

        # Fallback: buy offer anchor links
        if not buyers:
            for anchor in (
                soup.select("a[href*='/buy-offers/']") +
                soup.select("a[href*='/company/']")
            )[:settings.MAX_RESULTS_PER_SOURCE]:
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
        logger.error("tradewheel: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["United States"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            slug = _keyword_to_slug(keyword)
            url = f"{BASE_URL}/buy-offers/{slug}/"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("tradewheel: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "United States"
                    buyers = _parse_tradewheel_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("tradewheel: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("tradewheel: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    # Fallback: use site search endpoint
                    alt_url = f"{BASE_URL}/search/?q={quote_plus(keyword)}&type=buyer"
                    await asyncio.sleep(random.uniform(1, 2))
                    resp2 = await client.get(alt_url, headers=_get_headers())
                    if resp2.status_code == 200:
                        target_country = countries[0] if countries else "United States"
                        buyers = _parse_tradewheel_results(resp2.text, keyword, target_country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                    else:
                        logger.info("tradewheel: no results", keyword=keyword)
                else:
                    logger.warning("tradewheel: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("tradewheel: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("tradewheel: request error", error=str(e))
            except Exception as e:
                logger.error("tradewheel: unexpected error", error=str(e))

    logger.info("tradewheel: scrape complete", total=len(all_buyers))
    return all_buyers
