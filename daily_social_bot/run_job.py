"""
GitHub Actions 入口 — 执行一次完整的抓取/筛选/生成/推送流程
"""
import logging
import sys
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    all_items = []

    # 1a. HackerNews
    try:
        from fetchers.twitter_fetcher import TwitterFetcher
        tw_cfg = config["sources"]["twitter"]
        items = TwitterFetcher().fetch_accounts(tw_cfg["accounts"], tw_cfg["max_per_account"])
        all_items.extend(items)
        logger.info(f"HackerNews: {len(items)} items")
    except Exception as e:
        logger.error(f"HackerNews fetch failed: {e}")

    # 1b. RSS 订阅（36kr / 虎嗅 / 少数派 / Product Hunt 等）
    try:
        from fetchers.xhs_fetcher import XHSFetcher
        rss_cfg = config["sources"].get("rss", {})
        feeds = rss_cfg.get("feeds", [])
        max_per = rss_cfg.get("max_per_feed", 5)
        if feeds:
            items = XHSFetcher().fetch_feeds(feeds, max_per)
            all_items.extend(items)
            logger.info(f"RSS: {len(items)} items")
    except Exception as e:
        logger.error(f"RSS fetch failed: {e}")

    # 1c. X/Twitter 关注账号（via RSSHub / Nitter）
    try:
        from fetchers.twitter_rss_fetcher import fetch_all_users
        tw_users_cfg = config["sources"].get("twitter_users", {})
        accounts = tw_users_cfg.get("accounts", [])
        max_per_user = tw_users_cfg.get("max_per_account", 3)
        if accounts:
            items = fetch_all_users(accounts, max_per_user)
            all_items.extend(items)
            logger.info(f"Twitter users: {len(items)} tweets from {len(accounts)} accounts")
    except Exception as e:
        logger.error(f"Twitter user fetch failed: {e}")

    if not all_items:
        logger.error("No items fetched — exit")
        sys.exit(1)

    logger.info(f"Total items: {len(all_items)}")

    # 2. AI 筛选
    from ai.selector import select_best
    selected = select_best(all_items, config["selector"]["criteria"])
    if not selected:
        logger.error("Selector returned nothing — exit")
        sys.exit(1)
    logger.info(f"Selected: [{selected.source_type}] {selected.title[:60]}")

    # 3. 生成推文
    from ai.generator import generate_tweets
    gen = config["generator"]
    tweets = generate_tweets(selected, gen["style"], gen["tweet_count"])
    if not tweets:
        logger.error("Generator returned no tweets — exit")
        sys.exit(1)

    # 4. 发飞书卡片
    from notifier.feishu import send_daily_drafts
    ok = send_daily_drafts(tweets, selected.title, selected.url)
    if ok:
        logger.info("Feishu card sent — waiting for confirmation")
    else:
        logger.error("Failed to send Feishu card")
        sys.exit(1)


if __name__ == "__main__":
    main()
