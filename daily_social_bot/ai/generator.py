"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    source_block = f"【原文标题】{content.title}"
    if content.body and len(content.body.strip()) > 20:
        source_block += f"\n【原文内容】{content.body[:800]}"

    prompt = f"""你是一个在做一人公司的创业者。你今天读了几个不同博主的内容，现在要写出你自己的判断——不是转述任何一个人，而是把这些内容触发的你自己的想法表达出来。

{source_block}

{style_guide}

要求：
- 这几条内容来自不同的人，把它们触发的洞察融合成你自己的观点，不要引用或转述任何一个具体人
- 写 {count} 条推文，分别是：暴论型、反直觉型、踩坑/感悟型
- 每条200-350字，短句换行，有节奏感，层次清晰
- 每条推文聚焦一个清晰的判断，不要什么都说

【硬性禁止】
- 不许提某个博主的名字或账号
- 不许写"数据显示""研究表明""有人说"
- 不许编造产品名、工具名
- 不许堆砌大词：重塑、赋能、颠覆、范式

输出 JSON 数组，包含 {count} 个字符串。只输出数组，不要其他内容。"""

    raw = call_llm(prompt, max_tokens=1500)
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        tweets = json.loads(raw)
        if isinstance(tweets, list):
            result = []
            for t in tweets[:count]:
                if isinstance(t, dict):
                    t = t.get("text") or t.get("tweet") or t.get("content") or str(t)
                result.append(str(t))
            return result
    except Exception as e:
        logger.error(f"Generator parse error: {e}\nRaw: {raw}")
    return []
