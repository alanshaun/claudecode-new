"""
LLM 客户端 — 优先 Gemini，回退 Kimi
"""
import os
import logging

logger = logging.getLogger(__name__)


def call_llm(prompt: str, max_tokens: int = 1500) -> str:
    kimi_key = os.environ.get("KIMI_API_KEY", "")
    if kimi_key:
        return _call_kimi(prompt, max_tokens, kimi_key)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        return _call_gemini(prompt, max_tokens, gemini_key)
    raise RuntimeError("No LLM API key found (KIMI_API_KEY or GEMINI_API_KEY)")


def _call_gemini(prompt: str, max_tokens: int, api_key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={"max_output_tokens": max_tokens, "temperature": 0.9},
    )
    resp = model.generate_content(prompt)
    return resp.text.strip()


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
