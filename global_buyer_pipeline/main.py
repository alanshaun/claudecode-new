#!/usr/bin/env python3
"""
global_buyer_pipeline 主入口
仅用于 GitHub Actions，按 --mode 执行不同管道
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import get_logger

logger = get_logger()


async def run_daily():
    """每日：Comtrade + OpenCorporates，限制 5000"""
    from pipelines.comtrade import run as comtrade_run
    from pipelines.opencorporates import run as oc_run
    cfg = {"limit": 5000}
    total = 0
    total += await comtrade_run(cfg)
    total += await oc_run(cfg)
    return total


async def run_weekly():
    """每周：所有来源，限制 50000"""
    cfg = {"limit": 50000}
    total = 0
    from pipelines.comtrade import run as r1
    from pipelines.us_customs import run as r2
    from pipelines.india_trade import run as r3
    from pipelines.brazil_trade import run as r4
    from pipelines.eurostat import run as r5
    from pipelines.exhibitions import run as r6
    from pipelines.opencorporates import run as r7

    for name, fn in [("comtrade", r1), ("us_customs", r2), ("india_trade", r3), ("brazil_trade", r4),
                    ("eurostat", r5), ("exhibitions", r6), ("opencorporates", r7)]:
        try:
            if asyncio.iscoroutinefunction(fn):
                n = await fn(cfg)
            else:
                n = fn(cfg)
            total += n
            logger.info("来源 %s 完成，本次 %d 条", name, n)
        except Exception as e:
            logger.exception("来源 %s 异常", name, error=str(e))
    return total


def run_email_enrichment(limit: int = 1000):
    """邮箱补全"""
    from enrichment.email_enrichment import run
    return run(limit=limit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "email"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.mode == "daily":
        n = asyncio.run(run_daily())
    elif args.mode == "weekly":
        n = asyncio.run(run_weekly())
    else:
        n = run_email_enrichment(limit=args.limit or 1000)

    logger.info("完成，本次入库/补全：%d 条", n)


if __name__ == "__main__":
    main()
