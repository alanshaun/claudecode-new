"""
GlobalMatch scrapers package - 20个全球买家数据源
"""
from scrapers import (
    alibaba_rfq_scraper, ec21_scraper, europages_scraper,
    exporthub_scraper, exportersindia_scraper, google_scraper,
    hoovers_scraper, importyeti_scraper, kellysearch_scraper,
    kompass_scraper, linkedin_scraper, piers_scraper,
    thomasnet_scraper, tradearabia_scraper, tradeindia_scraper,
    tradekey_scraper, tradewheel_scraper, wlw_scraper,
    yellowpages_scraper, zawya_scraper,
)

SCRAPER_REGISTRY: dict = {
    "importyeti":     importyeti_scraper.scrape,
    "kompass":        kompass_scraper.scrape,
    "alibaba_rfq":    alibaba_rfq_scraper.scrape,
    "google":         google_scraper.scrape,
    "europages":      europages_scraper.scrape,
    "yellowpages":    yellowpages_scraper.scrape,
    "tradeindia":     tradeindia_scraper.scrape,
    "ec21":           ec21_scraper.scrape,
    "linkedin":       linkedin_scraper.scrape,
    "piers":          piers_scraper.scrape,
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
