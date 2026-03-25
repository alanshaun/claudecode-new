"""
Twitter / X 抓取器 — 通过 Nitter RSS 读取推文（无需付费 API）
多个 Nitter 实例轮询，任一可用即止
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.lucabased.xyz",
    "https://nitter.net",
]


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


def _fetch_rss(username: str, max_count: int) -> list[Tweet]:
    for base in NITTER_INSTANCES:
        url = f"{base}/{username}/rss"
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.text)
            if not feed.entries:
                continue

            tweets = []
            for entry in feed.entries[:max_count]:
                title = entry.get("title", "")
                if title.startswith("RT by"):
                    continue
                try:
                    created = parsedate_to_datetime(entry.get("published", ""))
                except Exception:
                    created = datetime.now(timezone.utc)

                link = entry.get("link", "")
                tweet_id = link.split("/")[-1] if link else ""
                summary = entry.get("summary", "")
                text = re.sub(r"<[^>]+>", "", summary).strip()

                tweets.append(Tweet(
                    id=tweet_id,
                    author=username,
                    text=text or title,
                    created_at=created,
                    url=f"https://x.com/{username}/status/{tweet_id}",
                ))

            logger.info(f"Twitter RSS @{username}: {len(tweets)} tweets via {base}")
            return tweets

        except Exception as e:
            logger.warning(f"Nitter {base} failed for @{username}: {e}")
            continue

    logger.error(f"All Nitter instances failed for @{username}")
    return []


class TwitterFetcher:
    def fetch_accounts(self, accounts: list[str], max_per_account: int = 10) -> list[Tweet]:
        all_tweets: list[Tweet] = []
        for username in accounts:
            tweets = _fetch_rss(username, max_per_account)
            all_tweets.extend(tweets)
        logger.info(f"Twitter total: {len(all_tweets)} tweets from {accounts}")
        return all_tweets
