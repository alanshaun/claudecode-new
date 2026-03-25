"""
GitHub Actions 入口 — 话题轮转模式
每次运行从预设话题列表里取一个，生成推文发飞书确认
"""
import datetime
import logging
import sys
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 话题池 — 围绕一人公司 / AI / 商业 / 内容变现
TOPICS = [
    "一人公司的工具链和成本控制：用最低的固定成本搭起能赚钱的系统",
    "AI工具的真实效率：哪些真的改变了工作方式，哪些是噱头",
    "精准小流量 vs 泛流量陷阱：粉丝数不等于变现能力",
    "冷启动的具体打法：从0到第一批付费用户怎么走",
    "定价心理学：为什么大多数独立开发者把产品卖便宜了",
    "一人公司的决策逻辑：时间、精力、钱，怎么分配才不亏",
    "内容分发的本质：什么平台值得深耕，什么时候该放弃",
    "需求验证：动手做之前，怎么知道有人愿意付钱",
    "复利思维：内容、产品、用户关系，哪些东西会随时间增值",
    "独立创业的心路：一个人做所有决策，背所有锅，也拿100%利润",
    "AI替代人力的真实账本：具体省了多少钱、多少时间",
    "社群变现 vs 广告变现：哪种模式更适合一人公司",
    "产品冷启动的分发渠道选择：从第一个用户到第一百个",
    "创业中的沉没成本陷阱：什么时候应该放弃一个方向",
    "一人公司的竞争优势：小就是快，快就是护城河",
]


def pick_topic(topics: list[str]) -> str:
    now = datetime.datetime.now()
    # 用「今天是第几天 × 5 + 当前时段」做偏移，确保同一天5次运行话题各不同
    hour_slot = {9: 0, 10: 0, 11: 1, 12: 1, 13: 2, 14: 2, 15: 2, 16: 3, 17: 3, 18: 3, 19: 4, 20: 4, 21: 4, 22: 4}.get(now.hour, 0)
    idx = (now.timetuple().tm_yday * 5 + hour_slot) % len(topics)
    return topics[idx]


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    # 1. 选话题
    topics = config.get("topics", TOPICS)
    topic = pick_topic(topics)
    logger.info(f"Today's topic: {topic}")

    # 2. 生成推文
    from ai.generator import generate_tweets
    from ai.selector import SelectedContent

    content = SelectedContent(
        source_type="topic",
        title=topic,
        body="",
        url="",
        reason=topic,
    )
    gen = config["generator"]
    tweets = generate_tweets(content, gen["style"], gen["tweet_count"])
    if not tweets:
        logger.error("Generator returned no tweets — exit")
        sys.exit(1)
    logger.info(f"Generated {len(tweets)} tweets")

    # 3. 发飞书卡片
    from notifier.feishu import send_daily_drafts
    ok = send_daily_drafts(tweets, topic, "")
    if ok:
        logger.info("Feishu card sent — waiting for confirmation")
    else:
        logger.error("Failed to send Feishu card")
        sys.exit(1)


if __name__ == "__main__":
    main()
