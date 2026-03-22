"""
TradeArabia.com scraper - Middle East trade news & company directory
URL: https://www.tradearabia.com/website/search.asp?q={keyword}
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

SOURCE_NAME = "tradearabia"
BASE_URL = "https://www.tradearabia.com"


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
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_tradearabia_results(html: str, keyword: str, country: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # TradeArabia search results - typically table or div-based
        cards = (
            soup.select("div[class*='result']")
            or soup.select("div[class*='listing']")
            or soup.select("table.search-results tr")
            or soup.select("div[class*='company']")
            or soup.select("li[class*='result']")
            or soup.select("div[class*='search-item']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                name_el = (
                    card.select_one("h2[class*='title']")
                    or card.select_one("h3[class*='title']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("a[class*='title']")
                    or card.select_one("td[class*='name']")
                    or card.select_one("h2")
                    or card.select_one("h3")
                    or card.select_one("strong")
                    or card.select_one("b")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name or len(company_name) < 2:
                    continue

                # Website link
                link_el = (
                    card.select_one("a[href*='/website/']")
                    or card.select_one("a[href*='/company/']")
                    or card.select_one("a[class*='website']")
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
                loc_el = (
                    card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("[class*='region']")
                )
                detected_country = loc_el.get_text(strip=True) if loc_el else country

                # Category / sector
                cat_el = (
                    card.select_one("[class*='category']")
                    or card.select_one("[class*='sector']")
                    or card.select_one("[class*='industry']")
                )
                category = cat_el.get_text(strip=True) if cat_el else ""

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                # Phone numbers (may be WhatsApp in ME)
                phone_match = re.search(r"(?:\+971|\+966|\+974|\+965|\+973|\+968|\+962|\+961)[\s\-]?\d[\d\s\-]{7,}", card_text)
                whatsapp = phone_match.group(0).strip() if phone_match else ""

                categories = [keyword]
                if category and category != keyword:
                    categories.append(category)

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=detected_country,
                    website=website,
                    email=email,
                    whatsapp=whatsapp,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("tradearabia: card parse error", error=str(e))
                continue

        # Fallback: news articles mentioning companies
        if not buyers:
            for anchor in soup.select("a[href*='/website/']")[:settings.MAX_RESULTS_PER_SOURCE]:
                try:
                    name = anchor.get_text(strip=True)
                    href = anchor.get("href", "")
                    if name and len(name) > 2 and not name.lower().startswith("read"):
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
        logger.error("tradearabia: parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    if not countries:
        countries = ["UAE"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            url = f"{BASE_URL}/website/search.asp?q={quote_plus(keyword)}"

            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("tradearabia: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    target_country = countries[0] if countries else "UAE"
                    buyers = _parse_tradearabia_results(resp.text, keyword, target_country)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["country"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("tradearabia: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("tradearabia: rate limited", status=resp.status_code)
                    await asyncio.sleep(20)
                elif resp.status_code == 404:
                    logger.info("tradearabia: no results", keyword=keyword)
                else:
                    logger.warning("tradearabia: unexpected status", status=resp.status_code, url=url)

            except httpx.TimeoutException:
                logger.warning("tradearabia: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("tradearabia: request error", error=str(e))
            except Exception as e:
                logger.error("tradearabia: unexpected error", error=str(e))

    logger.info("tradearabia: scrape complete", total=len(all_buyers))
    return all_buyers
