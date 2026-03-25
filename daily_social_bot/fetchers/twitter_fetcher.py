"""
Twitter / X 抓取器
使用 Twitter API v2 via tweepy
"""
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import tweepy

logger = logging.getLogger(__name__)


@dataclass
class Tweet:
    id: str
    author: str
    text: str
    created_at: datetime
    like_count: int
    retweet_count: int
    reply_count: int
    url: str

    @property
    def engagement(self) -> int:
        return self.like_count + self.retweet_count * 2 + self.reply_count


class TwitterFetcher:
    def __init__(self):
        bearer = os.environ["TWITTER_BEARER_TOKEN"]
        self.client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=True)

    def fetch_accounts(self, accounts: list[str], max_per_account: int = 10) -> list[Tweet]:
        """抓取指定账号近 24 小时内的推文"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        tweets: list[Tweet] = []

        for username in accounts:
            try:
                user_resp = self.client.get_user(username=username)
                if not user_resp.data:
                    logger.warning(f"User not found: {username}")
                    continue
                user_id = user_resp.data.id

                resp = self.client.get_users_tweets(
                    id=user_id,
                    max_results=max_per_account,
                    start_time=cutoff,
                    tweet_fields=["created_at", "public_metrics", "text"],
                    exclude=["retweets", "replies"],
                )
                if not resp.data:
                    continue

                for t in resp.data:
                    m = t.public_metrics or {}
                    tweets.append(Tweet(
                        id=str(t.id),
                        author=username,
                        text=t.text,
                        created_at=t.created_at,
                        like_count=m.get("like_count", 0),
                        retweet_count=m.get("retweet_count", 0),
                        reply_count=m.get("reply_count", 0),
                        url=f"https://x.com/{username}/status/{t.id}",
                    ))
            except Exception as e:
                logger.error(f"Failed to fetch tweets for @{username}: {e}")

        logger.info(f"Twitter: fetched {len(tweets)} tweets from {accounts}")
        return tweets
