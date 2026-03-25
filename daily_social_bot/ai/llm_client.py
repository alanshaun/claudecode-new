"""
LLM 客户端 — Gemini (主, google-generativeai SDK) + Kimi (备)
"""
import os
import time
import logging

logger = logging.getLogger(__name__)

KIMI_API_BASE = "https://api.moonshot.cn/v1"
KIMI_MODEL = "moonshot-v1-8k"
GEMINI_MODEL = "gemini-1.5-flash"


def _call_gemini(prompt: str, max_tokens: int = 1024) -> str:
    import google.generativeai as genai
    key = os.environ.get("GEMINI_API_KEY", "")
    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"max_output_tokens": max_tokens},
    )
    resp = model.generate_content(prompt)
    return resp.text.strip()


def _call_kimi(prompt: str, max_tokens: int = 1024) -> str:
    import httpx
    key = os.environ.get("KIMI_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": KIMI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    for attempt in range(5):
        resp = httpx.post(
            f"{KIMI_API_BASE}/chat/completions",
            json=payload, headers=headers, timeout=30,
        )
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            logger.warning(f"Kimi 429, waiting {wait}s ({attempt+1}/5)")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("Kimi rate limit exceeded after 5 retries")


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    try:
        result = _call_gemini(prompt, max_tokens)
        logger.info("LLM: Gemini OK")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed ({e}), trying Kimi")
        return _call_kimi(prompt, max_tokens)
