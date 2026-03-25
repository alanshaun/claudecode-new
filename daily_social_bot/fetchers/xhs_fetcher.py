"""
小红书抓取器
使用登录 Cookie 调用小红书 Web API
"""
import os
import logging
import hashlib
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

XHS_SEARCH_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
XHS_NOTE_URL = "https://www.xiaohongshu.com/explore/{note_id}"


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
            "Referer": "https://www.xiaohongshu.com/",
            "Origin": "https://www.xiaohongshu.com",
        }

    def _sign_request(self, uri: str, data: dict) -> dict:
        """
        小红书请求需要 x-s / x-t 签名。
        此处返回空签名头作为占位 — 生产环境需集成签名算法
        （可参考 https://github.com/ReaJason/xhs 或自行抓包）。
        """
        ts = str(int(time.time() * 1000))
        return {"x-s": "", "x-t": ts}

    def search_keyword(self, keyword: str, max_count: int = 5) -> list[XHSNote]:
        notes: list[XHSNote] = []
        payload = {
            "keyword": keyword,
            "page": 1,
            "page_size": max_count,
            "search_id": hashlib.md5(keyword.encode()).hexdigest(),
            "sort": "hot",          # hot = 最热; time = 最新
            "note_type": 0,
        }
        sign = self._sign_request(XHS_SEARCH_URL, payload)
        headers = {**self.headers, **sign}

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(XHS_SEARCH_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            items = data.get("data", {}).get("items", [])
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
                    liked_count=int(interact.get("liked_count", "0") or 0),
                    collected_count=int(interact.get("collected_count", "0") or 0),
                    url=XHS_NOTE_URL.format(note_id=note_id),
                ))
        except Exception as e:
            logger.error(f"XHS search failed for '{keyword}': {e}")

        return notes

    def fetch_keywords(self, keywords: list[str], max_per_keyword: int = 5) -> list[XHSNote]:
        all_notes: list[XHSNote] = []
        for kw in keywords:
            notes = self.search_keyword(kw, max_per_keyword)
            all_notes.extend(notes)
            logger.info(f"XHS '{kw}': {len(notes)} notes")
        return all_notes
