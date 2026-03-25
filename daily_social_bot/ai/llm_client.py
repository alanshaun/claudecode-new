"""
统一 LLM 客户端 — Gemini (主) + Kimi (备)
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

KIMI_API_BASE = "https://api.moonshot.cn/v1"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

KIMI_MODEL = "moonshot-v1-8k"
GEMINI_MODEL = "gemini-2.0-flash"


def _call_gemini(prompt: str, max_tokens: int = 1024) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    resp = httpx.post(url, json=payload, timeout=30)
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
    resp = httpx.post(f"{KIMI_API_BASE}/chat/completions", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    """Gemini 优先，失败自动切 Kimi"""
    try:
        result = _call_gemini(prompt, max_tokens)
        logger.info("LLM: used Gemini")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed ({e}), falling back to Kimi")
        result = _call_kimi(prompt, max_tokens)
        logger.info("LLM: used Kimi")
        return result
