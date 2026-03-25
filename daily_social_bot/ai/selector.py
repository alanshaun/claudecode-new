"""
内容筛选器 — 用 Claude 从抓取结果中选最值得发的一条
"""
import json
import logging
from dataclasses import dataclass
from typing import Union

import anthropic

from fetchers.twitter_fetcher import Tweet
from fetchers.xhs_fetcher import XHSNote

logger = logging.getLogger(__name__)

ContentItem = Union[Tweet, XHSNote]


@dataclass
class SelectedContent:
    source_type: str          # "twitter" | "xiaohongshu"
    title: str
    body: str
    url: str
    reason: str               # Claude 选择理由


def _format_items(items: list[ContentItem]) -> str:
    lines = []
    for i, item in enumerate(items):
        if isinstance(item, Tweet):
            lines.append(
                f"[{i}] 来源=Twitter  作者=@{item.author}\n"
                f"    内容={item.text}\n"
                f"    互动={item.like_count}赞/{item.retweet_count}转/{item.reply_count}评\n"
                f"    链接={item.url}"
            )
        else:
            lines.append(
                f"[{i}] 来源=小红书   作者={item.author}\n"
                f"    标题={item.title}\n"
                f"    内容={item.desc[:200]}\n"
                f"    互动={item.liked_count}赞/{item.collected_count}收藏\n"
                f"    链接={item.url}"
            )
    return "\n\n".join(lines)


def select_best(
    items: list[ContentItem],
    criteria: str,
    model: str = "claude-opus-4-6",
) -> SelectedContent | None:
    if not items:
        logger.warning("No items to select from")
        return None

    client = anthropic.Anthropic()
    prompt = f"""你是一个科技/创业领域的内容策展人。

筛选标准：
{criteria}

以下是今日抓取的内容列表（共 {len(items)} 条）：
{_format_items(items)}

请选出最值得转发传播的 **一条**，输出 JSON：
{{
  "index": <列表序号>,
  "reason": "<50字内说明选择理由>"
}}

只输出 JSON，不要其他文字。"""

    resp = client.messages.create(
        model=model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    try:
        data = json.loads(raw)
        idx = int(data["index"])
        item = items[idx]
        if isinstance(item, Tweet):
            return SelectedContent(
                source_type="twitter",
                title=f"@{item.author}",
                body=item.text,
                url=item.url,
                reason=data.get("reason", ""),
            )
        else:
            return SelectedContent(
                source_type="xiaohongshu",
                title=item.title,
                body=item.desc,
                url=item.url,
                reason=data.get("reason", ""),
            )
    except Exception as e:
        logger.error(f"Failed to parse selector response: {e}\nRaw: {raw}")
        return None
