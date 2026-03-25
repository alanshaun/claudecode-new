"""
推文生成器 — 用 Claude 按用户风格生成 N 条候选推文
"""
import json
import logging

import anthropic

from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(
    content: SelectedContent,
    style_guide: str,
    count: int = 3,
    model: str = "claude-opus-4-6",
) -> list[str]:
    """返回 count 条候选推文文本列表"""
    client = anthropic.Anthropic()

    prompt = f"""你是一个帮助用户写推文的助手。

原始素材：
标题/作者：{content.title}
内容：{content.body}
来源链接：{content.url}
策展理由：{content.reason}

{style_guide}

请基于这条素材，写 {count} 条风格各有侧重的推文。
输出严格为 JSON 数组，例如：
["推文1内容", "推文2内容", "推文3内容"]

只输出 JSON 数组，不要序号、标题或其他文字。"""

    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    try:
        tweets = json.loads(raw)
        if isinstance(tweets, list):
            return [str(t) for t in tweets[:count]]
    except Exception as e:
        logger.error(f"Failed to parse generator response: {e}\nRaw: {raw}")
    return []
