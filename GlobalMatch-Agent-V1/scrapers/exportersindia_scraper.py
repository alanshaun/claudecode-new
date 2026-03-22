"""
ExportersIndia.com scraper - India B2B buyers & exporters directory
URL: https://www.exportersindia.com/{keyword}-buyers.html
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

SOURCE_NAME = "exportersindia"
BASE_URL = "https://www.exportersindia.com"


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
    """Convert keyword to ExportersIndia URL slug format."""
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower().strip()).strip("-")


def _parse_exportersindia_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # ExportersIndia buyer listing entries
        cards = (
            soup.select("div[class*='buyer-detail']")
            or soup.select("div[class*='buyerdetail']")
            or soup.select("div[class*='listing-item']")
            or soup.select("div[class*='company-box']")
            or soup.select("ul[class*='buyer'] li")
            or soup.select("div[class*='prod-box']")
            or soup.select("div.bxsl")
            or soup.select("div[class*='bxsl']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company name
                name_el = (
                    card.select_one("h3[class*='buyer']")
                    or card.select_one("h2[class*='company']")
                    or card.select_one("a[class*='company']")
                    or card.select_one("[class*='comp-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Profile link
                link_el = (
                    card.select_one("a[href*='/buyer/']")
                    or card.select_one("a[href*='/company/']")
                    or card.select_one("a[href*='/profile/']")
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
                    or card.select_one("[class*='city']")
                    or card.select_one("[class*='country']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Product / requirement text
                req_el = (
                    card.select_one("[class*='requirement']")
                    or card.select_one("[class*='product']")
                    or card.select_one("p")
                )
                requirement = req_el.get_text(strip=True) if req_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                # Indian phone numbers (potential WhatsApp)
                phone_match = re.search(r"(?:\+91|0)?[6-9]\d{9}", card_text.replace(" ", "").replace("-", ""))
                whatsapp = phone_match.group(0).strip() if phone_match else ""

                categories = [keyword]
                if requirement and len(requirement) > 3 and requirement != keyword:
                    categories.append(requirement[:80])

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country or "India",
                    website=website,
                    email=email,
                    whatsapp=whatsapp,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("exportersindia: card parse error", error=str(e))
                continue

        # Fallback: buyer anchor links
        if not buyers:
            for anchor in soup.select("a[href*='-buyers']")[:settings.MAX_RESULTS_PER_SOURCE]:
                try:
                    name = anchor.get_text(strip=True)
                    href = anchor.get("href", "")
                    if name and len(name) > 2:
                        website = href if href.startswith("http") else BASE_URL + href
                        buyers.append(_make_buyer(
                            company_name=name,
                            country=country or "India",
                            website=website,
                            categories=[keyword],
                        ))
                except Exception:
                    continue

    except Exception as e:
        logger.error("exportersindia: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["India"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            slug = _keyword_to_slug(keyword)
            url = f"{BASE_URL}/{slug}-buyers.html"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("exportersindia: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "India"
                    buyers = _parse_exportersindia_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("exportersindia: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("exportersindia: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    # Try alternative URL: /search?q={keyword}&type=buyer
                    alt_url = f"{BASE_URL}/search?q={quote_plus(keyword)}&type=buyer"
                    await asyncio.sleep(random.uniform(1, 2))
                    resp2 = await client.get(alt_url, headers=_get_headers())
                    if resp2.status_code == 200:
                        target_country = countries[0] if countries else "India"
                        buyers = _parse_exportersindia_results(resp2.text, keyword, target_country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                    else:
                        logger.info("exportersindia: no results", keyword=keyword)
                else:
                    logger.warning("exportersindia: unexpected status",
                                   status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("exportersindia: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("exportersindia: request error", error=str(e))
            except Exception as e:
                logger.error("exportersindia: unexpected error", error=str(e))

    logger.info("exportersindia: scrape complete", total=len(all_buyers))
    return all_buyers
