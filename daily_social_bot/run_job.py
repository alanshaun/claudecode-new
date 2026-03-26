"""
GitHub Actions 入口 — 混合模式
优先从博主 Twitter RSS + 博客 RSS 抓素材，不够则用话题兜底
"""
import datetime
import logging
import sys
import yaml
from dotenv import load_dotenv
load_dotenv()

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

    # 1. 从缓存取3条不同来源的素材
    from content_cache import get_next_items

    def _fetch():
        return fetch_content(config)

    raw_items = get_next_items(5, _fetch)
    logger.info(f"Using {len(raw_items)} cached items from: {[it['source'] for it in raw_items]}")

    from ai.generator import generate_tweets
    from ai.selector import SelectedContent

    if raw_items:
        # 把多条素材合并，生成器会融合它们
        combined_title = " / ".join(it["title"][:40] for it in raw_items)
        combined_body = "\n\n---\n\n".join(
            f"[{it['source']}] {it['title']}\n{it['body'][:300]}" for it in raw_items
        )
        content = SelectedContent(
            source_type="external",
            title=combined_title,
            body=combined_body,
            url="",
            reason=f"来自 {len(raw_items)} 个来源",
        )
        topic_label = " · ".join(it["source"] for it in raw_items)
    else:
        # 缓存为空兜底 → 话题轮转
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

    # 4. 发飞书，让用户自己选一条发到推特
    from notifier.feishu import send_drafts
    send_drafts(tweets, topic_label)
    logger.info("Drafts sent to Feishu")


if __name__ == "__main__":
    main()
