"""
Exporthub.com scraper - Global buyers & buying leads directory
URL: https://www.exporthub.com/buying-leads/{keyword}/
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

SOURCE_NAME = "exporthub"
BASE_URL = "https://www.exporthub.com"


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
        "Cache-Control": "max-age=0",
    }


def _keyword_to_slug(keyword: str) -> str:
    """Convert keyword to Exporthub URL slug (hyphen-separated, lowercase)."""
    return re.sub(r"[^a-z0-9]+", "-", keyword.lower().strip()).strip("-")


def _parse_exporthub_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Exporthub buying-lead listing cards
        cards = (
            soup.select("div[class*='buying-lead']")
            or soup.select("div[class*='BuyingLead']")
            or soup.select("div[class*='lead-item']")
            or soup.select("li[class*='lead']")
            or soup.select("div[class*='product-box']")
            or soup.select("div[class*='listing-item']")
            or soup.select("article[class*='lead']")
            or soup.select("div[class*='buyer-card']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Buyer / company name
                name_el = (
                    card.select_one("[class*='buyer-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='member-name']")
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

                # Profile / lead detail link
                link_el = (
                    card.select_one("a[href*='/buying-leads/']")
                    or card.select_one("a[href*='/company/']")
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
                    or card.select_one("[class*='origin']")
                )
                detected_country = ""
                if country_el:
                    detected_country = country_el.get("title", "") or country_el.get_text(strip=True)
                if not detected_country:
                    detected_country = country

                # Quantity / requirement description
                desc_el = (
                    card.select_one("[class*='description']")
                    or card.select_one("[class*='requirement']")
                    or card.select_one("[class*='details']")
                    or card.select_one("p")
                )
                description = desc_el.get_text(strip=True) if desc_el else ""

                # Date posted (for freshness awareness - just log it)
                date_el = card.select_one("[class*='date']") or card.select_one("time")
                post_date = date_el.get_text(strip=True) if date_el else ""

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
                logger.warning("exporthub: card parse error", error=str(e))
                continue

        # Fallback: any buying-lead anchor links
        if not buyers:
            for anchor in (
                soup.select("a[href*='/buying-leads/']") +
                soup.select("a[href*='/company/']")
            )[:settings.MAX_RESULTS_PER_SOURCE]:
                try:
                    name = anchor.get_text(strip=True)
                    href = anchor.get("href", "")
                    # Skip navigation / pagination links
                    if name and len(name) > 2 and not name.isdigit():
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
        logger.error("exporthub: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["United States"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            slug = _keyword_to_slug(keyword)
            url = f"{BASE_URL}/buying-leads/{slug}/"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("exporthub: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "United States"
                    buyers = _parse_exporthub_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("exporthub: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("exporthub: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    # Fallback: use site search endpoint
                    alt_url = f"{BASE_URL}/search/?q={quote_plus(keyword)}&category=buying-leads"
                    await asyncio.sleep(random.uniform(1, 2))
                    resp2 = await client.get(alt_url, headers=_get_headers())
                    if resp2.status_code == 200:
                        target_country = countries[0] if countries else "United States"
                        buyers = _parse_exporthub_results(resp2.text, keyword, target_country)
                        for b in buyers:
                            key = (b["company_name"].lower(), b["country"].lower())
                            if key not in seen and b["company_name"]:
                                seen.add(key)
                                all_buyers.append(b)
                    else:
                        logger.info("exporthub: no results", keyword=keyword)
                else:
                    logger.warning("exporthub: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("exporthub: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("exporthub: request error", error=str(e))
            except Exception as e:
                logger.error("exporthub: unexpected error", error=str(e))

    logger.info("exporthub: scrape complete", total=len(all_buyers))
    return all_buyers
