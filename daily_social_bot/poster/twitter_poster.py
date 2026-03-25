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
    api_key = os.environ["TWITTER_API_KEY"]
    api_secret = os.environ["TWITTER_API_SECRET"]
    access_token = os.environ["TWITTER_ACCESS_TOKEN"]
    access_token_secret = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

    # 打印凭证前缀，方便排查哪个凭证是错的
    logger.info(f"API Key prefix: {api_key[:8]}...")
    logger.info(f"Access Token prefix: {access_token[:20]}...")

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )
    try:
        resp = client.create_tweet(text=text)
    except tweepy.errors.Unauthorized as e:
        logger.error(f"Twitter 401 detail: {e.response.text if hasattr(e, 'response') else e}")
        raise
    tweet_id = resp.data["id"]
    me = client.get_me()
    username = me.data.username if me.data else "unknown"
    url = f"https://x.com/{username}/status/{tweet_id}"
    logger.info(f"Posted tweet: {url}")
    return url
