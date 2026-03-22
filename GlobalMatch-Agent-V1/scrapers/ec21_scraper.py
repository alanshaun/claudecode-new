"""
EC21.com scraper - Korea-origin, pan-Asia B2B marketplace.
URL: https://www.ec21.com/buyers/?query={keyword}
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

SOURCE_NAME = "ec21"


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
        "Referer": "https://www.ec21.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_ec21_html(html: str, keyword: str) -> list[dict]:
    buyers = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # JSON-LD data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Organization", "LocalBusiness"):
                        name = item.get("name", "")
                        if name:
                            buyers.append(_make_buyer(
                                company_name=name,
                                country=item.get("addressCountry", ""),
                                website=item.get("url", ""),
                                email=item.get("email", ""),
                                categories=[keyword],
                            ))
            except Exception:
                continue

        # Buyer listing rows / cards
        cards = (
            soup.select("div.buyer-item")
            or soup.select("div[class*='buyer-item']")
            or soup.select("ul.buyer-list > li")
            or soup.select("div[class*='item_buyer']")
            or soup.select("div.co_list_item")
            or soup.select("div[class*='company-item']")
            or soup.select("li[class*='item']")
        )

        for card in cards[:settings.MAX_RESULTS_PER_SOURCE]:
            try:
                # Company / buyer name
                name_el = (
                    card.select_one("[class*='buyer-name']")
                    or card.select_one("[class*='company-name']")
                    or card.select_one("[class*='co_name']")
                    or card.select_one("h3") or card.select_one("h2")
                    or card.select_one("strong")
                    or card.select_one("a")
                )
                company_name = name_el.get_text(strip=True) if name_el else ""
                if not company_name:
                    continue

                # Website / profile link
                link_el = card.select_one("a[href*='/buyer/'], a[href*='/company/']")
                if not link_el:
                    link_el = card.select_one("a[href]")
                website = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("http"):
                        website = href
                    elif href.startswith("/"):
                        website = "https://www.ec21.com" + href

                # Country flag / location
                country_el = (
                    card.select_one("[class*='flag']")
                    or card.select_one("[class*='country']")
                    or card.select_one("[class*='location']")
                    or card.select_one("span[title]")
                )
                country = ""
                if country_el:
                    # Try title attribute for flag spans
                    country = country_el.get("title") or country_el.get_text(strip=True)
                    country = re.sub(r"[^\x00-\x7F]+", "", country).strip()

                # Product / category
                product_el = (
                    card.select_one("[class*='product']")
                    or card.select_one("[class*='category']")
                    or card.select_one("p")
                )
                product = product_el.get_text(strip=True) if product_el else ""
                categories = [product, keyword] if product and product != keyword else [keyword]

                card_text = card.get_text()
                emails = extract_emails_from_text(card_text)
                email = emails[0] if emails else ""

                buyers.append(_make_buyer(
                    company_name=company_name,
                    country=country,
                    website=website,
                    email=email,
                    categories=categories,
                ))
            except Exception as e:
                logger.warning("ec21: card parse error", error=str(e))
                continue

        # Fallback: look for window.__DATA__ or similar JS data
        if not buyers:
            for script in soup.find_all("script"):
                script_text = script.string or ""
                if "buyer" in script_text.lower() and ("companyName" in script_text or "company_name" in script_text):
                    try:
                        match = re.search(r'window\.__(?:DATA|INIT_DATA|STATE)__\s*=\s*({.+?});', script_text, re.DOTALL)
                        if match:
                            data = json.loads(match.group(1))
                            buyer_list = (
                                data.get("buyerList") or data.get("list") or
                                data.get("buyers") or []
                            )
                            for item in buyer_list[:settings.MAX_RESULTS_PER_SOURCE]:
                                name = item.get("companyName") or item.get("company_name") or item.get("name", "")
                                if name:
                                    buyers.append(_make_buyer(
                                        company_name=name,
                                        country=item.get("country", ""),
                                        website=item.get("website") or item.get("url", ""),
                                        email=item.get("email", ""),
                                        categories=[keyword],
                                    ))
                    except Exception:
                        continue

    except Exception as e:
        logger.error("ec21: HTML parse failed", error=str(e))

    return buyers


async def scrape(keywords: list[str], countries: list[str], buyer_types: list[str]) -> list[dict]:
    all_buyers = []
    seen = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for keyword in keywords:
            url = f"https://www.ec21.com/buyers/?query={quote_plus(keyword)}"
            try:
                await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                logger.info("ec21: fetching", url=url)

                resp = await client.get(url, headers=_get_headers())

                if resp.status_code == 200:
                    buyers = _parse_ec21_html(resp.text, keyword)
                    for b in buyers:
                        key = (b["company_name"].lower(), b["website"].lower())
                        if key not in seen and b["company_name"]:
                            seen.add(key)
                            all_buyers.append(b)
                    logger.info("ec21: found buyers", keyword=keyword, count=len(buyers))
                elif resp.status_code in (403, 429):
                    logger.warning("ec21: rate limited", status=resp.status_code)
                    await asyncio.sleep(12)
                else:
                    logger.warning("ec21: unexpected status", status=resp.status_code, url=url)

                # Also try the company/seller listings for supplemental results
                if not all_buyers:
                    company_url = f"https://www.ec21.com/company/?query={quote_plus(keyword)}"
                    await asyncio.sleep(random.uniform(settings.SCRAPER_DELAY_MIN, settings.SCRAPER_DELAY_MAX))
                    try:
                        resp2 = await client.get(company_url, headers=_get_headers())
                        if resp2.status_code == 200:
                            more = _parse_ec21_html(resp2.text, keyword)
                            for b in more:
                                key = (b["company_name"].lower(), b["website"].lower())
                                if key not in seen and b["company_name"]:
                                    seen.add(key)
                                    all_buyers.append(b)
                    except Exception as e:
                        logger.warning("ec21: company fallback error", error=str(e))

            except httpx.TimeoutException:
                logger.warning("ec21: timeout", url=url)
            except httpx.RequestError as e:
                logger.error("ec21: request error", error=str(e))
            except Exception as e:
                logger.error("ec21: unexpected error", keyword=keyword, error=str(e))

    logger.info("ec21: scrape complete", total=len(all_buyers))
    return all_buyers
