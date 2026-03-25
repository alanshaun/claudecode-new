"""
RSS 抓取器 — 36kr / 虎嗅 / 少数派 / Product Hunt 等
无需登录，从任何 IP 均可访问
"""
import logging
import re
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)


@dataclass
class XHSNote:
    id: str
    title: str
    desc: str
    author: str
    liked_count: int
    collected_count: int
    url: str

    @property
    def engagement(self) -> int:
        return self.liked_count + self.collected_count * 2


class XHSFetcher:
    def __init__(self):
        pass

    def fetch_feeds(self, feeds: list[dict], max_per_feed: int = 5) -> list[XHSNote]:
        """feeds: [{"url": "...", "name": "..."}]"""
        notes: list[XHSNote] = []
        seen: set[str] = set()

        for feed_cfg in feeds:
            url = feed_cfg.get("url", "")
            name = feed_cfg.get("name", url)
            try:
                resp = httpx.get(url, timeout=12, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; RSS reader)"})
                feed = feedparser.parse(resp.text)
                count = 0
                for entry in feed.entries:
                    if count >= max_per_feed:
                        break
                    entry_id = entry.get("id") or entry.get("link", "")
                    if entry_id in seen:
                        continue
                    seen.add(entry_id)

                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", ""))
                    desc = re.sub(r"<[^>]+>", "", summary).strip()[:400]
                    link = entry.get("link", "")
                    author = entry.get("author", name)

                    notes.append(XHSNote(
                        id=entry_id,
                        title=title,
                        desc=desc,
                        author=author,
                        liked_count=0,
                        collected_count=0,
                        url=link,
                    ))
                    count += 1

                logger.info(f"RSS [{name}]: {count} items")
            except Exception as e:
                logger.error(f"RSS fetch failed [{name}] {url}: {e}")

        return notes

    def fetch_keywords(self, keywords: list[str], max_per_keyword: int = 5) -> list[XHSNote]:
        """兼容旧接口"""
        return []
