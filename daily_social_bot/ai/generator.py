"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    topic = content.title

    prompt = f"""你是一个在做一人公司的创业者，在 X 上分享自己的真实思考和商业判断。

今天的话题：{topic}

{style_guide}

写 {count} 条推文，角度分别用：暴论型、反直觉型、心路历程型。

【硬性禁止】
- 不许编造产品名、公司名、工具名（不要出现 TurboQuant、XYZ平台 等虚构名词）
- 不许写"今天遇到一件事""我看到一篇文章"——只写观点、判断、原则
- 不许写新闻报道口吻，不许转述别人的事

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
