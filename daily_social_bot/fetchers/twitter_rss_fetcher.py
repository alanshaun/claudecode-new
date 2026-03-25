"""
X/Twitter 用户推文抓取器 — 通过 RSSHub / Nitter 转 RSS
按顺序尝试多个公共实例，第一个成功的就用
"""
import logging
import re
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)

# 按可靠性排序，第一个能用就停
RSS_TEMPLATES = [
    "https://rsshub.app/twitter/user/{username}",
    "https://nitter.privacydev.net/{username}/rss",
    "https://nitter.poast.org/{username}/rss",
    "https://nitter.1d4.us/{username}/rss",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSS reader)"}


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

    # 与 XHSNote / Tweet 共用 selector 格式
    @property
    def engagement(self):
        return 0


def fetch_user_tweets(username: str, max_count: int = 3) -> list[UserTweet]:
    for template in RSS_TEMPLATES:
        url = template.format(username=username)
        try:
            resp = httpx.get(url, timeout=12, follow_redirects=True, headers=HEADERS)
            if resp.status_code != 200:
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

                items.append(UserTweet(
                    id=entry_id,
                    author=f"@{username}",
                    title=title,
                    desc=desc,
                    url=link,
                ))

            logger.info(f"Twitter RSS [@{username}] via {url.split('/')[2]}: {len(items)} tweets")
            return items
        except Exception as e:
            logger.debug(f"Twitter RSS [@{username}] {url}: {e}")
            continue

    logger.warning(f"Twitter RSS [@{username}]: all sources failed, skipping")
    return []


def fetch_all_users(accounts: list[str], max_per_account: int = 3) -> list[UserTweet]:
    results = []
    for username in accounts:
        results.extend(fetch_user_tweets(username, max_per_account))
    return results
