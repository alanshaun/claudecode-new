"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def _extract_topic(content: SelectedContent) -> str:
    """把具体文章标题提炼成抽象话题方向，去掉产品/项目名。"""
    prompt = f"""把下面这条内容的核心话题，提炼成1-2句话的思考方向。
要求：去掉所有具体产品名/公司名/项目名，只保留抽象的主题和关键数字。

原标题：{content.title}
背景：{content.body[:300]}
策展理由：{content.reason}

直接输出提炼后的话题方向，不要其他内容。"""
    result = call_llm(prompt, max_tokens=150)
    return result.strip() or content.reason


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    topic = _extract_topic(content)

    prompt = f"""你是一个在做一人公司的创业者，今天想写 X 推文，分享自己对 AI/一人公司/商业 的真实思考。

今天想聊的话题方向：
{topic}

{style_guide}

写 {count} 条推文，角度分别是：暴论型、反直觉型、感悟型。

【必须做到】
- 写的是你自己的想法和判断，不是在转述任何文章或工具
- 每条有「我」或强开头（「说个暴论」「说实话」「我越来越相信」）
- 有至少一个具体数字（钱、时间、比例）
- 结尾是一句有力的个人结论，不是大道理

【正面示例】
"说个暴论：半年前我还在想是不是要买 A100。
现在整个 AI 工作流跑在 $50/月 的 VPS 上。
成本降了 95%，一分钟能处理的请求量反而翻了三倍。
一人公司最大的误判，是以为 AI 基础设施很贵。"

输出 JSON 数组，包含 {count} 个字符串。只输出数组，不要其他内容。"""

    raw = call_llm(prompt, max_tokens=1500)
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        tweets = json.loads(raw)
        if isinstance(tweets, list):
            result = []
            for t in tweets[:count]:
                # 有时 AI 返回 {"text": "..."} 对象而非字符串
                if isinstance(t, dict):
                    t = t.get("text") or t.get("tweet") or t.get("content") or str(t)
                result.append(str(t))
            return result
    except Exception as e:
        logger.error(f"Generator parse error: {e}\nRaw: {raw}")
    return []
