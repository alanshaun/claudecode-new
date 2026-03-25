"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    prompt = f"""你是一个在 X（Twitter）上有真实洞察力的科技博主。

今日素材：
标题：{content.title}
内容：{content.body[:800]}
来源：{content.url}
策展理由：{content.reason}

{style_guide}

基于以上素材，写 {count} 条推文。每条要求：
- 2~4 句话，有实质内容，不是标题复读
- 说出自己的判断或观点，不是"某某技术很厉害"这种废话
- 可以用类比、反常识视角、具体数字、追问等手法
- 不同条之间角度要有差异（比如：一条讲技术意义，一条讲商业影响，一条讲用户角度）

输出 JSON 数组：["推文1", "推文2", "推文3"]
只输出数组，不要其他内容。"""

    raw = call_llm(prompt, max_tokens=1500)
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        tweets = json.loads(raw)
        if isinstance(tweets, list):
            return [str(t) for t in tweets[:count]]
    except Exception as e:
        logger.error(f"Generator parse error: {e}\nRaw: {raw}")
    return []
