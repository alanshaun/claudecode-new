"""
GlobalMatch scrapers package.

Exports every scraper module and a registry dict mapping
source name -> scrape coroutine for easy dynamic dispatch.
"""
from scrapers import (
    alibaba_rfq_scraper,
    europages_scraper,
    google_scraper,
    importyeti_scraper,
    kompass_scraper,
    tradeindia_scraper,
    yellowpages_scraper,
    thomasnet_scraper,
    hoovers_scraper,
    wlw_scraper,
    kellysearch_scraper,
    zawya_scraper,
    tradearabia_scraper,
    exportersindia_scraper,
    tradekey_scraper,
    tradewheel_scraper,
    exporthub_scraper,
)

# Registry: source name -> async scrape(keywords, countries, buyer_types) function
SCRAPER_REGISTRY: dict = {
    "alibaba_rfq":    alibaba_rfq_scraper.scrape,
    "europages":      europages_scraper.scrape,
    "google":         google_scraper.scrape,
    "importyeti":     importyeti_scraper.scrape,
    "kompass":        kompass_scraper.scrape,
    "tradeindia":     tradeindia_scraper.scrape,
    "yellowpages":    yellowpages_scraper.scrape,
    "thomasnet":      thomasnet_scraper.scrape,
    "hoovers":        hoovers_scraper.scrape,
    "wlw":            wlw_scraper.scrape,
    "kellysearch":    kellysearch_scraper.scrape,
    "zawya":          zawya_scraper.scrape,
    "tradearabia":    tradearabia_scraper.scrape,
    "exportersindia": exportersindia_scraper.scrape,
    "tradekey":       tradekey_scraper.scrape,
    "tradewheel":     tradewheel_scraper.scrape,
    "exporthub":      exporthub_scraper.scrape,
}

__all__ = [
    "alibaba_rfq_scraper",
    "europages_scraper",
    "google_scraper",
    "importyeti_scraper",
    "kompass_scraper",
    "tradeindia_scraper",
    "yellowpages_scraper",
    "thomasnet_scraper",
    "hoovers_scraper",
    "wlw_scraper",
    "kellysearch_scraper",
    "zawya_scraper",
    "tradearabia_scraper",
    "exportersindia_scraper",
    "tradekey_scraper",
    "tradewheel_scraper",
    "exporthub_scraper",
    "SCRAPER_REGISTRY",
]
