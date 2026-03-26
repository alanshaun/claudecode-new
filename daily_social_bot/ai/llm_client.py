"""
LLM 客户端 — Kimi
"""
import os
import logging

logger = logging.getLogger(__name__)


def call_llm(prompt: str, max_tokens: int = 1500) -> str:
    kimi_key = os.environ.get("KIMI_API_KEY", "")
    if not kimi_key:
        raise RuntimeError("KIMI_API_KEY not set")
    return _call_kimi(prompt, max_tokens, kimi_key)


def _call_kimi(prompt: str, max_tokens: int, api_key: str) -> str:
    import httpx, time
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    for attempt in range(3):
        resp = httpx.post(
            "https://api.moonshot.cn/v1/chat/completions",
            json=payload, headers=headers, timeout=30,
        )
        if resp.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("Kimi rate limit exceeded")
