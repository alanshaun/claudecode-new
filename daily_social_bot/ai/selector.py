"""
内容筛选器
"""
import json
import logging
from dataclasses import dataclass
from typing import Union

from ai.llm_client import call_llm
from fetchers.twitter_fetcher import Tweet
from fetchers.xhs_fetcher import XHSNote

logger = logging.getLogger(__name__)
ContentItem = Union[Tweet, XHSNote]


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
            body_preview = getattr(item, 'body', '')[:400] if getattr(item, 'body', '') else ''
            lines.append(
                f"[{i}] 标题={item.text}\n"
                f"    热度={item.like_count}赞/{item.reply_count}评论\n"
                f"    评论摘要={body_preview}\n"
                f"    链接={item.url}"
            )
        else:
            lines.append(
                f"[{i}] 标题={item.title}\n"
                f"    内容={item.desc[:300]}\n"
                f"    链接={item.url}"
            )
    return "\n\n".join(lines)


def select_best(items: list[ContentItem], criteria: str, **_) -> SelectedContent | None:
    if not items:
        return None

    prompt = f"""你是 AI/创业/产品领域的内容策展人。

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
                source_type="twitter",
                title=item.text,
                body=body,
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
