"""
Twitter / X 发布器
使用 OAuth 1.0a（需要 API Key + Access Token）
"""
import os
import logging

import tweepy

logger = logging.getLogger(__name__)


def post_tweet(text: str) -> str:
    """发布推文，返回推文 URL"""
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )
    resp = client.create_tweet(text=text)
    tweet_id = resp.data["id"]
    # 获取自己的 username
    me = client.get_me()
    username = me.data.username if me.data else "unknown"
    url = f"https://x.com/{username}/status/{tweet_id}"
    logger.info(f"Posted tweet: {url}")
    return url
