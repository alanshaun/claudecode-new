"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    prompt = f"""你是一个真实的人，正在写自己的 X（Twitter）推文。

今日发现的内容：
标题：{content.title}
正文：{content.body[:800]}
（来源链接不需要写进推文，发布时会自动附上）

{style_guide}

用这条内容写 {count} 条推文草稿。

【铁律，违反即重写】
1. 必须有"我"作主语，或以"刚看到"、"今天发现"、"推荐一个"、"一直在想"这类第一人称开头
2. 禁止出现：「这意味着」「这不仅仅是」「某某技术/公司的X，标志着Y」等新闻播报句式
3. 禁止总结别人的观点，要说自己的感受、判断、疑问、或从中联想到的事
4. 每条 6~12 行，有具体细节，不是一句话大道理
5. 三条角度不同：可以是「发现分享」「个人判断」「带出一个更大的问题」

好开头示例：
- "刚看到一个…"
- "我一直搞不懂为什么…直到今天看到这个"
- "这周让我印象最深的一件事："
- "推荐一个…，我自己在用"
- "有个问题我想了很久："
- "说实话，我当时看到这个数字吓了一跳："

输出 JSON 数组，包含 {count} 个字符串。只输出数组，不要其他内容。"""

    raw = call_llm(prompt, max_tokens=1500)
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        tweets = json.loads(raw)
        if isinstance(tweets, list):
            return [str(t) for t in tweets[:count]]
    except Exception as e:
        logger.error(f"Generator parse error: {e}\nRaw: {raw}")
    return []
