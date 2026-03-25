"""
Daily Social Automation — 主入口
启动后：
  1. 运行 FastAPI 回调服务器（接收企业微信回复）
  2. APScheduler 每天 09:00 执行一次抓取 → 筛选 → 生成 → 推送流程
"""
import logging
import os
import sys
import threading

import uvicorn
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_daily_job(config: dict) -> None:
    """每日任务主逻辑"""
    logger.info("=== Daily job started ===")

    # 1. 抓取内容
    all_items = []

    tw_cfg = config["sources"]["twitter"]
    try:
        from fetchers.twitter_fetcher import TwitterFetcher
        tw = TwitterFetcher()
        all_items.extend(tw.fetch_accounts(tw_cfg["accounts"], tw_cfg["max_per_account"]))
    except Exception as e:
        logger.error(f"Twitter fetch failed: {e}")

    xhs_cfg = config["sources"]["xiaohongshu"]
    try:
        from fetchers.xhs_fetcher import XHSFetcher
        xhs = XHSFetcher()
        all_items.extend(xhs.fetch_keywords(xhs_cfg["keywords"], xhs_cfg["max_per_keyword"]))
    except Exception as e:
        logger.error(f"XHS fetch failed: {e}")

    if not all_items:
        logger.warning("No items fetched — aborting today's job")
        return

    logger.info(f"Total items fetched: {len(all_items)}")

    # 2. AI 筛选最佳内容
    from ai.selector import select_best
    sel_cfg = config["selector"]
    selected = select_best(all_items, sel_cfg["criteria"], sel_cfg["model"])
    if not selected:
        logger.warning("Selector returned nothing — aborting")
        return
    logger.info(f"Selected: [{selected.source_type}] {selected.title}")

    # 3. 生成候选推文
    from ai.generator import generate_tweets
    gen_cfg = config["generator"]
    tweets = generate_tweets(selected, gen_cfg["style"], gen_cfg["tweet_count"], gen_cfg["model"])
    if not tweets:
        logger.warning("Generator returned no tweets — aborting")
        return
    logger.info(f"Generated {len(tweets)} tweet drafts")

    # 4. 注册确认回调
    def on_confirm(tweet: str) -> None:
        from poster.twitter_poster import post_tweet
        from notifier.wecom import send_text
        try:
            url = post_tweet(tweet)
            send_text(f"✅ 推文已发布！\n{url}\n\n内容：{tweet}")
        except Exception as e:
            logger.error(f"Post failed: {e}")
            from notifier.feishu import send_text
            send_text(f"❌ 发布失败：{e}")

    from server.callback import set_pending
    set_pending(tweets, on_confirm)

    # 5. 推送草稿到飞书
    from notifier.feishu import send_daily_drafts
    ok = send_daily_drafts(tweets, selected.title, selected.url)
    if ok:
        logger.info("Drafts sent to WeChat — waiting for user confirmation")
    else:
        logger.error("Failed to send drafts to WeChat")

    # 6. 超时自动清除（避免旧状态污染下一天）
    timeout = config["poster"]["confirm_timeout_minutes"] * 60

    def _clear_after_timeout():
        import time as _time
        _time.sleep(timeout)
        from server.callback import _pending
        if _pending.get("tweets"):
            logger.info("Confirmation timed out — clearing pending state")
            _pending["tweets"] = []
            _pending["on_confirm"] = None

    threading.Thread(target=_clear_after_timeout, daemon=True).start()
    logger.info(f"=== Daily job finished (timeout={timeout}s) ===")


def main():
    config = load_config()

    # 启动 FastAPI 回调服务器（后台线程）
    from server.callback import app as callback_app
    port = int(os.environ.get("CALLBACK_SERVER_PORT", 8080))

    def _run_server():
        uvicorn.run(callback_app, host="0.0.0.0", port=port, log_level="warning")

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()
    logger.info(f"Callback server started on port {port}")

    # 启动调度器
    sch_cfg = config["schedule"]
    scheduler = BackgroundScheduler(timezone=sch_cfg["timezone"])
    scheduler.add_job(
        run_daily_job,
        trigger="cron",
        hour=sch_cfg["hour"],
        minute=sch_cfg["minute"],
        args=[config],
        id="daily_social",
    )
    scheduler.start()
    logger.info(
        f"Scheduler started — next run at {sch_cfg['hour']:02d}:{sch_cfg['minute']:02d} "
        f"({sch_cfg['timezone']})"
    )

    # 支持立即运行（调试用）
    if "--run-now" in sys.argv:
        logger.info("--run-now flag detected, executing job immediately")
        run_daily_job(config)

    # 主线程保持运行
    try:
        server_thread.join()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
