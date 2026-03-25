"""
内容筛选器
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Union

from ai.llm_client import call_llm
from fetchers.twitter_fetcher import Tweet
from fetchers.twitter_rss_fetcher import UserTweet
from fetchers.xhs_fetcher import XHSNote

logger = logging.getLogger(__name__)
ContentItem = Union[Tweet, XHSNote, UserTweet]

# 关键词预过滤 — 至少命中一个才进入 AI 筛选
_KEEP_KEYWORDS = [
    # AI
    "ai", "llm", "gpt", "claude", "gemini", "agent", "模型", "大模型", "人工智能",
    "openai", "anthropic", "mistral", "ollama", "rag", "embedding", "推理",
    # 创业/产品
    "创业", "startup", "founder", "indie", "solopreneur", "一人公司", "产品",
    "saas", "bootstrap", "indiehacker", "side project", "副业", "变现", "monetize",
    # 增长/冷启动
    "增长", "growth", "冷启动", "获客", "用户", "arr", "mrr", "revenue", "收入",
    # 开发者工具/GitHub
    "github", "open source", "开源", "developer", "工具", "framework",
    # 趋势/洞察
    "trend", "insight", "分析", "调研", "报告",
]

_BLOCK_KEYWORDS = [
    "激光雷达", "vcsel", "芯片制造", "晶圆", "半导体制程", "股价", "期货", "大盘",
    "房地产", "楼市", "医疗", "药物", "基因", "政策", "监管", "外交",
]


def _prefilter(items: list[ContentItem]) -> list[ContentItem]:
    """粗过滤：去掉明显不相关的内容，保留可能相关的"""
    kept = []
    for item in items:
        text = ""
        if isinstance(item, Tweet):
            text = (item.text + " " + getattr(item, 'body', '')).lower()
        elif isinstance(item, UserTweet):
            text = (item.title + " " + item.desc).lower()
        else:
            text = (item.title + " " + item.desc).lower()

        # 有屏蔽词直接丢
        if any(kw in text for kw in _BLOCK_KEYWORDS):
            continue
        # 有保留词才留下
        if any(kw in text for kw in _KEEP_KEYWORDS):
            kept.append(item)

    logger.info(f"Prefilter: {len(items)} → {len(kept)} items")
    # 如果过滤太猛（<5条），降级回全量
    return kept if len(kept) >= 5 else items


@dataclass
class SelectedContent:
    source_type: str
    title: str
    body: str       # 原文内容 + 评论
    url: str
    reason: str


def _format_items(items: list[ContentItem]) -> str:
    lines = []
    for i, item in enumerate(items):
        if isinstance(item, Tweet):
            body_preview = getattr(item, 'body', '')[:300] if getattr(item, 'body', '') else ''
            lines.append(
                f"[{i}] [{item.author}] {item.text}\n"
                f"    热度={item.like_count}赞/{item.reply_count}评论\n"
                f"    讨论={body_preview}\n"
                f"    链接={item.url}"
            )
        elif isinstance(item, UserTweet):
            lines.append(
                f"[{i}] [{item.author}] {item.title}\n"
                f"    内容={item.desc[:300]}\n"
                f"    链接={item.url}"
            )
        else:
            lines.append(
                f"[{i}] [{getattr(item, 'author', 'RSS')}] {item.title}\n"
                f"    内容={item.desc[:300]}\n"
                f"    链接={item.url}"
            )
    return "\n\n".join(lines)


def select_best(items: list[ContentItem], criteria: str, **_) -> SelectedContent | None:
    if not items:
        return None

    items = _prefilter(items)

    prompt = f"""你是 AI/创业/产品/独立开发领域的内容策展人，只关注这些领域。

筛选标准：
{criteria}

今日内容（共 {len(items)} 条）：
{_format_items(items)}

选出最值得深度评论的一条，输出 JSON：
{{"index": <序号>, "reason": "<说明为什么这条值得评论，有什么讨论价值>"}}

只输出 JSON。"""

    raw = call_llm(prompt, max_tokens=300)
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        data = json.loads(raw)
        idx = int(data["index"])
        item = items[idx]
        if isinstance(item, Tweet):
            body = item.text
            if getattr(item, 'body', ''):
                body = f"{item.text}\n\n【社区讨论】\n{item.body}"
            return SelectedContent(
                source_type="hackernews",
                title=item.text,
                body=body,
                url=item.url,
                reason=data.get("reason", ""),
            )
        elif isinstance(item, UserTweet):
            return SelectedContent(
                source_type="twitter",
                title=item.title,
                body=f"{item.title}\n\n{item.desc}",
                url=item.url,
                reason=data.get("reason", ""),
            )
        else:
            return SelectedContent(
                source_type="rss",
                title=item.title,
                body=f"{item.title}\n\n{item.desc}",
                url=item.url,
                reason=data.get("reason", ""),
            )
    except Exception as e:
        logger.error(f"Selector parse error: {e}\nRaw: {raw}")
        return None
