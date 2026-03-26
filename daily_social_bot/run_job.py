"""
GitHub Actions 入口 — 混合模式
优先从博主 Twitter RSS + 博客 RSS 抓素材，不够则用话题兜底
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

# 话题池兜底用
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
    hour_slot = {9: 0, 10: 0, 11: 1, 12: 1, 13: 2, 14: 2, 15: 2, 16: 3, 17: 3, 18: 3, 19: 4, 20: 4, 21: 4, 22: 4}.get(now.hour, 0)
    idx = (now.timetuple().tm_yday * 5 + hour_slot) % len(topics)
    return topics[idx]


def fetch_content(config: dict) -> list:
    """抓 Twitter RSS + 博客 RSS，返回原始条目列表"""
    items = []

    # 1. Twitter 用户 RSS（Nitter）
    tw_cfg = config["sources"].get("twitter_users", {})
    if tw_cfg.get("enabled", False):
        from fetchers.twitter_rss_fetcher import fetch_all_users
        accounts = tw_cfg.get("accounts", [])
        max_per = tw_cfg.get("max_per_account", 3)
        tweets = fetch_all_users(accounts, max_per)
        logger.info(f"Twitter RSS: {len(tweets)} tweets from {len(accounts)} accounts")
        for t in tweets:
            items.append({
                "source": t.author,
                "title": t.text,
                "body": t.desc,
                "url": t.url,
            })

    # 2. 博客 RSS
    rss_cfg = config["sources"].get("rss", {})
    feeds = rss_cfg.get("feeds", [])
    max_per_feed = rss_cfg.get("max_per_feed", 3)
    if feeds:
        import feedparser, httpx, re
        for feed_info in feeds:
            try:
                resp = httpx.get(feed_info["url"], timeout=10, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 RSS Reader"})
                if resp.status_code != 200:
                    continue
                feed = feedparser.parse(resp.text)
                count = 0
                for entry in feed.entries:
                    if count >= max_per_feed:
                        break
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", ""))
                    body = re.sub(r"<[^>]+>", " ", summary).strip()[:600]
                    link = entry.get("link", "")
                    if title:
                        items.append({
                            "source": feed_info["name"],
                            "title": title,
                            "body": body,
                            "url": link,
                        })
                        count += 1
                logger.info(f"Blog RSS [{feed_info['name']}]: {count} entries")
            except Exception as e:
                logger.debug(f"Blog RSS [{feed_info['name']}]: {e}")

    return items


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    gen = config["generator"]

    # 1. 尝试抓外部素材
    raw_items = fetch_content(config)
    logger.info(f"Total raw items: {len(raw_items)}")

    from ai.generator import generate_tweets
    from ai.selector import SelectedContent, select_best
    from fetchers.twitter_rss_fetcher import UserTweet

    if len(raw_items) >= 3:
        # 2a. 有足够素材 → AI 选一条最有价值的，基于它写推文
        selector_items = [
            UserTweet(
                id=d["url"],
                author=d["source"],
                title=d["title"],
                desc=d["body"],
                url=d["url"],
            )
            for d in raw_items
        ]
        selected = select_best(selector_items, config["selector"]["criteria"])
        if selected:
            content = SelectedContent(
                source_type="external",
                title=selected.title,
                body=selected.body,
                url=selected.url,
                reason=f"来自 {selected.source}",
            )
            topic_label = f"{selected.source} · {selected.title[:40]}"
            logger.info(f"Selected: {topic_label}")
        else:
            # selector 没选出来，用话题兜底
            raw_items = []

    if len(raw_items) < 3:
        # 2b. 素材不够 → 话题兜底
        topics = config.get("topics", TOPICS)
        topic = pick_topic(topics)
        logger.info(f"Fallback to topic: {topic}")
        content = SelectedContent(
            source_type="topic",
            title=topic,
            body="",
            url="",
            reason=topic,
        )
        topic_label = topic

    # 3. 生成推文
    tweets = generate_tweets(content, gen["style"], gen["tweet_count"])
    if not tweets:
        logger.error("Generator returned no tweets — exit")
        sys.exit(1)
    logger.info(f"Generated {len(tweets)} tweets")

    # 4. 自动发布第一条
    from poster.twitter_poster import post_tweet
    from notifier.feishu import send_result, send_text
    try:
        tweet_url = post_tweet(tweets[0])
        logger.info(f"Posted: {tweet_url}")
        send_result(tweets[0], tweet_url, tweets[1:], topic_label)
    except Exception as e:
        logger.error(f"Post failed: {e}")
        send_text(f"❌ 发布失败：{e}\n\n草稿：\n" + "\n\n".join(tweets))
        sys.exit(1)


if __name__ == "__main__":
    main()
