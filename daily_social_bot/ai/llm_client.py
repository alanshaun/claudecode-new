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


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL = "gemini-1.5-flash-latest"


def _call_gemini(prompt: str, max_tokens: int = 1024) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    resp = httpx.post(url, json=payload, timeout=30)
    if not resp.is_success:
        logger.error(f"Gemini error {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_kimi(prompt: str, max_tokens: int = 1024) -> str:
    key = os.environ.get("KIMI_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": KIMI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    for attempt in range(4):
        resp = httpx.post(f"{KIMI_API_BASE}/chat/completions", json=payload, headers=headers, timeout=30)
        if resp.status_code == 429:
            wait = 20 * (attempt + 1)
            logger.warning(f"Kimi 429, waiting {wait}s (attempt {attempt+1}/4)")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("Kimi rate limit exceeded after 4 retries")


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    """Gemini 优先，失败切 Kimi"""
    try:
        result = _call_gemini(prompt, max_tokens)
        logger.info("LLM: Gemini OK")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed: {e}, trying Kimi")
        return _call_kimi(prompt, max_tokens)
