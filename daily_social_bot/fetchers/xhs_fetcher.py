"""
小红书抓取器 — 使用登录 Cookie 调用搜索接口
"""
import os
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class XHSNote:
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
        cookie = os.environ.get("XHS_COOKIE", "")
        if not cookie:
            raise ValueError("XHS_COOKIE is not set")
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Cookie": cookie,
            "Referer": "https://www.xiaohongshu.com/explore",
            "Origin": "https://www.xiaohongshu.com",
            "Content-Type": "application/json",
            "x-s": "",
            "x-t": "0",
        }

    def search_keyword(self, keyword: str, max_count: int = 5) -> list[XHSNote]:
        notes: list[XHSNote] = []
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes",
                    headers=self.headers,
                    json={
                        "keyword": keyword,
                        "page": 1,
                        "page_size": max_count,
                        "search_id": keyword,
                        "sort": "hot",
                        "note_type": 0,
                    },
                )
                data = resp.json()

            items = data.get("data", {}).get("items", [])
            logger.info(f"XHS '{keyword}': {len(items)} items (status {resp.status_code}), raw: {str(data)[:200]}")

            for item in items[:max_count]:
                note = item.get("note_card", {})
                note_id = item.get("id", "")
                if not note_id:
                    continue
                interact = note.get("interact_info", {})
                notes.append(XHSNote(
                    id=note_id,
                    title=note.get("display_title", ""),
                    desc=note.get("desc", ""),
                    author=note.get("user", {}).get("nickname", ""),
                    liked_count=int(re.sub(r"\D", "", str(interact.get("liked_count", "0"))) or 0),
                    collected_count=int(re.sub(r"\D", "", str(interact.get("collected_count", "0"))) or 0),
                    url=f"https://www.xiaohongshu.com/explore/{note_id}",
                ))
        except Exception as e:
            logger.error(f"XHS search failed for '{keyword}': {e}")

        return notes

    def fetch_keywords(self, keywords: list[str], max_per_keyword: int = 5) -> list[XHSNote]:
        all_notes: list[XHSNote] = []
        for kw in keywords:
            notes = self.search_keyword(kw, max_per_keyword)
            all_notes.extend(notes)
        return all_notes
