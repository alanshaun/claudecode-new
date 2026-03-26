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

    prompt = f"""你是一个在做一人公司的创业者，读完下面这篇内容后，写出你真实的感受和判断。

{source_block}

{style_guide}

要求：
- 你读的是真实内容，基于它发表你的看法，不要复述原文
- 写 {count} 条推文，分别是：暴论型、反直觉型、踩坑/感悟型
- 每条100-200字，短句换行，有节奏感

【硬性禁止】
- 不许编造产品名、公司名、工具名
- 不许写"做一人公司X个月"这种假经历——你没有，别编
- 不许写新闻报道口吻，不许说"数据显示""研究表明"
- 不许堆砌大词：不说"重塑""赋能""颠覆"

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
