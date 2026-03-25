"""
LLM 客户端 — Kimi (moonshot)，429 自动等待重试
"""
import os
import time
import logging
import httpx

logger = logging.getLogger(__name__)

KIMI_API_BASE = "https://api.moonshot.cn/v1"
KIMI_MODEL = "moonshot-v1-8k"


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    key = os.environ.get("KIMI_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": KIMI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }

    for attempt in range(4):
        resp = httpx.post(
            f"{KIMI_API_BASE}/chat/completions",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            logger.warning(f"Kimi 429 rate limit, waiting {wait}s (attempt {attempt+1}/4)")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    raise RuntimeError("Kimi rate limit exceeded after 4 retries")
