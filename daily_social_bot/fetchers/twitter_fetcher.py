"""
HackerNews 抓取器 — 使用 Algolia HN Search API
一次请求返回完整数据，无需逐条获取
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"


@dataclass
class Tweet:
    id: str
    author: str
    text: str
    created_at: datetime
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    url: str = ""

    @property
    def engagement(self) -> int:
        return self.like_count + self.retweet_count * 2 + self.reply_count


class TwitterFetcher:
    def fetch_accounts(self, accounts: list[str], max_per_account: int = 10) -> list[Tweet]:
        total = max(max_per_account, 15)
        return self._fetch_top(total)

    def _fetch_top(self, count: int) -> list[Tweet]:
        try:
            resp = httpx.get(
                ALGOLIA_URL,
                params={"tags": "front_page", "hitsPerPage": count},
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])

            items = []
            for hit in hits:
                title = hit.get("title", "")
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                score = hit.get("points", 0)
                comments = hit.get("num_comments", 0)
                author = hit.get("author", "")
                ts = hit.get("created_at_i", 0)

                items.append(Tweet(
                    id=str(hit.get("objectID", "")),
                    author=f"HN/{author}",
                    text=title,
                    created_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                    like_count=score,
                    reply_count=comments,
                    url=url,
                ))

            logger.info(f"HackerNews: fetched {len(items)} stories")
            return items
        except Exception as e:
            logger.error(f"HackerNews fetch failed: {e}")
            return []
