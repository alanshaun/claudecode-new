"""
HackerNews 抓取器 — 用 Algolia API 获取热帖 + 顶部评论作为上下文
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items"


@dataclass
class Tweet:
    id: str
    author: str
    text: str        # title
    body: str        # top comments / context
    created_at: datetime
    like_count: int = 0
    reply_count: int = 0
    url: str = ""

    @property
    def engagement(self) -> int:
        return self.like_count + self.reply_count


class TwitterFetcher:
    def fetch_accounts(self, accounts: list[str], max_per_account: int = 10) -> list[Tweet]:
        return self._fetch_top(max(max_per_account, 15))

    def _fetch_top(self, count: int) -> list[Tweet]:
        try:
            resp = httpx.get(
                ALGOLIA_SEARCH,
                params={"tags": "front_page", "hitsPerPage": count},
                timeout=15,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])

            items = []
            for hit in hits[:count]:
                story_id = hit.get("objectID", "")
                title = hit.get("title", "")
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                score = hit.get("points", 0)
                comments = hit.get("num_comments", 0)
                author = hit.get("author", "")
                ts = hit.get("created_at_i", 0)

                # 抓顶部评论作为文章背景
                body = self._fetch_top_comments(story_id)

                items.append(Tweet(
                    id=str(story_id),
                    author=f"HN/{author}",
                    text=title,
                    body=body,
                    created_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                    like_count=score,
                    reply_count=comments,
                    url=url,
                ))

            logger.info(f"HackerNews: fetched {len(items)} stories with comments")
            return items
        except Exception as e:
            logger.error(f"HackerNews fetch failed: {e}")
            return []

    def _fetch_top_comments(self, story_id: str, max_comments: int = 3) -> str:
        """抓前3条评论，作为文章讨论背景"""
        try:
            resp = httpx.get(f"{ALGOLIA_ITEM}/{story_id}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            children = data.get("children", [])
            comments = []
            for child in children[:max_comments]:
                text = child.get("text", "")
                if text and len(text) > 20:
                    # 去掉 HTML 标签
                    import re
                    text = re.sub(r"<[^>]+>", " ", text).strip()
                    comments.append(text[:300])
            return "\n---\n".join(comments)
        except Exception:
            return ""
