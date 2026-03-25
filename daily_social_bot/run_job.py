"""
GitHub Actions 入口 — 执行一次完整的抓取/筛选/生成/推送流程
"""
import logging
import sys
import yaml
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    # 1. 抓取
    all_items = []
    try:
        from fetchers.twitter_fetcher import TwitterFetcher
        tw_cfg = config["sources"]["twitter"]
        all_items.extend(TwitterFetcher().fetch_accounts(tw_cfg["accounts"], tw_cfg["max_per_account"]))
    except Exception as e:
        logger.error(f"Twitter fetch failed: {e}")

    try:
        from fetchers.xhs_fetcher import XHSFetcher
        xhs_cfg = config["sources"]["xiaohongshu"]
        all_items.extend(XHSFetcher().fetch_keywords(xhs_cfg["keywords"], xhs_cfg["max_per_keyword"]))
    except Exception as e:
        logger.error(f"XHS fetch failed: {e}")

    if not all_items:
        logger.error("No items fetched — exit")
        sys.exit(1)

    # 2. 筛选
    from ai.selector import select_best
    selected = select_best(all_items, config["selector"]["criteria"])
    if not selected:
        logger.error("Selector returned nothing — exit")
        sys.exit(1)

    # 3. 生成推文
    from ai.generator import generate_tweets
    gen = config["generator"]
    tweets = generate_tweets(selected, gen["style"], gen["tweet_count"])
    if not tweets:
        logger.error("Generator returned no tweets — exit")
        sys.exit(1)

    # 4. 发送飞书卡片（推文内容嵌入按钮，Render 回调时直接取用）
    from notifier.feishu import send_daily_drafts, send_text
    ok = send_daily_drafts(tweets, selected.title, selected.url)
    if ok:
        logger.info("Feishu card sent — waiting for user confirmation via Render")
    else:
        logger.error("Failed to send Feishu card")
        sys.exit(1)


if __name__ == "__main__":
    main()
