"""
内容缓存 — 每3天抓一次，存够15条素材
每次运行从缓存取一条，用完再抓
"""
import json
import logging
import os
import datetime

logger = logging.getLogger(__name__)
CACHE_FILE = os.path.join(os.path.dirname(__file__), "content_cache.json")
CACHE_DAYS = 3       # 每隔几天重新抓
CACHE_SIZE = 15      # 每次抓多少条（3天×5条）


def _load() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"fetched_at": None, "items": []}


def _save(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _is_stale(cache: dict) -> bool:
    if not cache.get("fetched_at"):
        return True
    fetched = datetime.datetime.fromisoformat(cache["fetched_at"])
    return (datetime.datetime.now() - fetched).days >= CACHE_DAYS


def get_next_items(n: int, fetch_fn) -> list[dict]:
    """
    取 n 条未使用的素材，尽量来自不同来源。
    缓存耗尽或超过3天，自动重新抓取。
    """
    cache = _load()
    unused = [item for item in cache.get("items", []) if not item.get("used")]

    if _is_stale(cache) or len(unused) < n:
        logger.info("Cache empty or stale, re-fetching content...")
        raw = fetch_fn()
        items = [dict(item, used=False) for item in raw[:CACHE_SIZE]]
        cache = {
            "fetched_at": datetime.datetime.now().isoformat(),
            "items": items,
        }
        _save(cache)
        unused = items
        logger.info(f"Cache refreshed: {len(items)} items stored")

    if not unused:
        return []

    # 尽量从不同 source 各取一条
    seen_sources = set()
    selected = []
    for item in unused:
        if item["source"] not in seen_sources:
            selected.append(item)
            seen_sources.add(item["source"])
        if len(selected) >= n:
            break
    # 不够就补
    for item in unused:
        if len(selected) >= n:
            break
        if item not in selected:
            selected.append(item)

    # 标记已使用
    used_urls = {it["url"] for it in selected}
    for i, it in enumerate(cache["items"]):
        if it["url"] in used_urls and not it.get("used"):
            cache["items"][i]["used"] = True
    _save(cache)
    return selected
