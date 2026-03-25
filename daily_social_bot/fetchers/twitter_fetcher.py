"""
HackerNews 抓取器（替代 Twitter/Nitter）
使用 HackerNews 官方免费 API，无需任何认证
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"


@dataclass
class Tweet:
    """保持与其他模块的接口兼容"""
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
    """从 HackerNews Top Stories 抓取内容"""

    def fetch_accounts(self, accounts: list[str], max_per_account: int = 10) -> list[Tweet]:
        """accounts 参数保留兼容性，实际抓取 HN Top Stories"""
        total = min(max_per_account * len(accounts), 30)
        return self._fetch_top(total)

    def _fetch_top(self, count: int) -> list[Tweet]:
        try:
            with httpx.Client(timeout=15) as client:
                ids = client.get(f"{HN_API}/topstories.json").json()[:count * 2]
                items = []
                for story_id in ids[:count * 3]:
                    if len(items) >= count:
                        break
                    try:
                        story = client.get(f"{HN_API}/item/{story_id}.json").json()
                        if not story or story.get("type") != "story":
                            continue
                        if not story.get("url") and not story.get("text"):
                            continue

                        title = story.get("title", "")
                        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                        score = story.get("score", 0)
                        comments = story.get("descendants", 0)
                        by = story.get("by", "")
                        ts = story.get("time", 0)

                        items.append(Tweet(
                            id=str(story_id),
                            author=f"HN/{by}",
                            text=title,
                            created_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                            like_count=score,
                            reply_count=comments,
                            url=url,
                        ))
                    except Exception:
                        continue

            logger.info(f"HackerNews: fetched {len(items)} stories")
            return items
        except Exception as e:
            logger.error(f"HackerNews fetch failed: {e}")
            return []
