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

    prompt = f"""你是一个在做一人公司的创业者，今天要发 X 推文，分享自己的真实经历、见闻、或者想明白的事。

今天想聊的话题方向（用来激发灵感，不要照抄，写自己的感受）：
{topic}

{style_guide}

写 {count} 条推文，分别用：暴论型、反直觉型、今日见闻型（或踩坑型）。

硬性要求（每条都要检查）：
1. 每条至少 2 个具体数字（金额/时间/比例/倍数）
2. 每条有 1~2 个颜文字，自然融入，不堆砌
3. 不说「这意味着」「值得学习」「让我们」这类套话
4. 不转述别人的文章——写的是你自己今天/这周经历的事或想到的事
5. 干货密度：每句话都要有信息量，没有废话段落

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
