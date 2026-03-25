"""
36kr RSS 抓取器（替代小红书）
公开 RSS，无需登录，从任何 IP 均可访问
"""
import logging
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)

# 36kr 各频道 RSS
KR36_FEEDS = {
    "AI创业":   "https://36kr.com/feed",
    "出海产品":  "https://36kr.com/feed",
}

# 也可用少数派
SSPAI_FEED = "https://sspai.com/feed"


@dataclass
class XHSNote:
    """保持与其他模块的接口兼容"""
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
        pass  # 不需要 Cookie

    def fetch_keywords(self, keywords: list[str], max_per_keyword: int = 5) -> list[XHSNote]:
        """从 36kr RSS 抓取最新文章"""
        notes: list[XHSNote] = []
        seen_ids: set[str] = set()
        total = max_per_keyword * len(keywords)

        feeds_to_try = [
            ("https://36kr.com/feed", "36kr"),
            (SSPAI_FEED, "少数派"),
        ]

        for feed_url, source_name in feeds_to_try:
            if len(notes) >= total:
                break
            try:
                resp = httpx.get(feed_url, timeout=10, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    if len(notes) >= total:
                        break
                    entry_id = entry.get("id") or entry.get("link", "")
                    if entry_id in seen_ids:
                        continue
                    seen_ids.add(entry_id)

                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    # 去除 HTML 标签
                    import re
                    desc = re.sub(r"<[^>]+>", "", summary).strip()[:300]
                    link = entry.get("link", "")
                    author = entry.get("author", source_name)

                    notes.append(XHSNote(
                        id=entry_id,
                        title=title,
                        desc=desc,
                        author=author,
                        liked_count=0,
                        collected_count=0,
                        url=link,
                    ))
                logger.info(f"{source_name} RSS: fetched {len(feed.entries)} entries")
            except Exception as e:
                logger.error(f"RSS fetch failed for {feed_url}: {e}")

        logger.info(f"Total RSS notes: {len(notes)}")
        return notes

    def search_keyword(self, keyword: str, max_count: int = 5) -> list[XHSNote]:
        return self.fetch_keywords([keyword], max_count)
