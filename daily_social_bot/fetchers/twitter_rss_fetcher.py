"""
X/Twitter 用户推文抓取器 — 通过多个 Nitter 实例转 RSS
按顺序尝试，第一个成功的就用
"""
import logging
import re
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)

# 按可靠性排序，持续维护中的实例优先
RSS_TEMPLATES = [
    "https://xcancel.com/{username}/rss",
    "https://nitter.privacydev.net/{username}/rss",
    "https://nitter.poast.org/{username}/rss",
    "https://nitter.net/{username}/rss",
    "https://nitter.cz/{username}/rss",
    "https://nitter.1d4.us/{username}/rss",
    "https://nitter.space/{username}/rss",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


@dataclass
class UserTweet:
    id: str
    author: str
    title: str
    desc: str
    url: str

    @property
    def text(self):
        return self.title or self.desc

    @property
    def engagement(self):
        return 0


def fetch_user_tweets(username: str, max_count: int = 3) -> list[UserTweet]:
    for template in RSS_TEMPLATES:
        url = template.format(username=username)
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True, headers=HEADERS)
            if resp.status_code != 200:
                logger.debug(f"[@{username}] {url.split('/')[2]}: HTTP {resp.status_code}")
                continue
            # 检查是否被重定向到无关页面
            if "google.com" in str(resp.url) or "404" in resp.url.path:
                continue
            feed = feedparser.parse(resp.text)
            if not feed.entries:
                continue

            items = []
            for entry in feed.entries[:max_count]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", ""))
                desc = re.sub(r"<[^>]+>", " ", summary).strip()[:500]
                link = entry.get("link", "")
                entry_id = entry.get("id") or link
                # 过滤转推（通常 title 以 "RT by" 开头）
                if title.startswith("RT by"):
                    continue
                items.append(UserTweet(
                    id=entry_id,
                    author=f"@{username}",
                    title=title,
                    desc=desc,
                    url=link,
                ))

            if items:
                logger.info(f"[@{username}] via {url.split('/')[2]}: {len(items)} tweets")
                return items
        except Exception as e:
            logger.debug(f"[@{username}] {url}: {e}")
            continue

    logger.warning(f"[@{username}]: all Nitter instances failed")
    return []


def fetch_all_users(accounts: list[str], max_per_account: int = 3) -> list[UserTweet]:
    results = []
    for username in accounts:
        tweets = fetch_user_tweets(username, max_per_account)
        results.extend(tweets)
    return results
