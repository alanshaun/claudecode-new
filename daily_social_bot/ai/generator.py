"""
推文生成器
"""
import json
import logging

from ai.llm_client import call_llm
from ai.selector import SelectedContent

logger = logging.getLogger(__name__)


def generate_tweets(content: SelectedContent, style_guide: str, count: int = 3, **_) -> list[str]:
    prompt = f"""你是一个在 X 上写作的创业者/独立开发者，正在写今天的推文。

今天看到的内容（用它来写推文，但要写成你自己的感受和判断，不是复述）：
标题：{content.title}
正文摘要：{content.body[:600]}

{style_guide}

写 {count} 条推文草稿，角度各不同（暴论型、反直觉型、发现分享型各选其一）。

检查清单（每条都要过，不过就重写）：
□ 有没有「我」或强开头（「说个暴论」「说实话」「刚看到」「一个反直觉」）？
□ 有没有至少一个具体数字或工具名？
□ 有没有以下烂尾/AI腔？有就删掉重写：
  - "这意味着…" / "标志着…"
  - "值得我们每一个X学习"
  - "不仅…也…"的套句
  - "这种X的思维，值得Y"
  - "让我意识到，为他们…不仅能…也是…"
  - "这种X让我确信，Y远超我们想象"
□ 结尾是否有劲？好结尾 = 一句自己的结论/反问/或让人想转发的话
□ 整体能量：读出来是否有力量感，还是像在写学生作文？
□ 有没有编造「我亲自做了XX」「我曾经XX」之类的虚假个人经历？有就改成「看到有人做了…」或第三方视角

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
