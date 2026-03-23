"""
搜索Agent - 协调所有爬虫，整合结果
支持：20数据源并行爬取、自动切换、去重、关键词扩展
"""
import asyncio
import structlog
import time
from typing import Optional, Callable

from config import settings, DATA_SOURCES_PRIORITY, TASK_MAX_DURATION_SECONDS
from utils.dedup import BuyerDeduplicator
from utils.email_validator import validate_emails_batch
from agent.kimi_client import kimi_client

logger = structlog.get_logger(__name__)


class SearchAgent:
    """
    全局买家搜索Agent
    协调20个数据源并行爬取，自动容错切换
    """

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.progress_callback = progress_callback
        self.deduplicator = BuyerDeduplicator()
        self._start_time = None

    async def search(self, search_params: dict, target_count: int = 100) -> list[dict]:
        """
        执行全球买家搜索
        search_params: Kimi分析结果
        target_count: 目标买家数量（100/200/300）
        """
        # 延迟导入避免循环引用
        from scrapers import SCRAPER_REGISTRY

        self._start_time = time.time()
        keywords = search_params.get("keywords_en", [])
        target_countries = search_params.get("target_countries", [])
        buyer_types = search_params.get("buyer_types", ["importer", "wholesaler"])

        logger.info("开始搜索", keywords=keywords, countries=target_countries, target=target_count)
        await self._update_progress(5, "正在启动20个数据源并行搜索...")

        all_buyers = []
        source_semaphore = asyncio.Semaphore(8)  # 最多8个数据源并发

        async def run_scraper(source_name: str) -> list[dict]:
            """运行单个爬虫，独立异常隔离"""
            async with source_semaphore:
                if self._is_timeout():
                    logger.warning("任务超时，停止新爬虫", source=source_name)
                    return []
                return await self._run_scraper_isolated(
                    source_name, SCRAPER_REGISTRY,
                    keywords, target_countries, buyer_types
                )

        # 并行运行所有数据源
        tasks = [run_scraper(source) for source in DATA_SOURCES_PRIORITY]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            source_name = DATA_SOURCES_PRIORITY[i] if i < len(DATA_SOURCES_PRIORITY) else "unknown"
            if isinstance(result, Exception):
                logger.error("爬虫任务异常", source=source_name, error=str(result))
            elif isinstance(result, list):
                all_buyers.extend(result)
                logger.info("数据源完成", source=source_name, count=len(result))

        await self._update_progress(70, f"爬取完成，共 {len(all_buyers)} 条原始数据，正在去重...")

        # 去重
        unique_buyers = self.deduplicator.deduplicate(all_buyers)
        logger.info("去重完成", raw=len(all_buyers), unique=len(unique_buyers))

        # 邮箱格式验证
        for buyer in unique_buyers:
            if buyer.get("email"):
                emails = validate_emails_batch([buyer["email"]])
                buyer["email"] = emails[0] if emails else ""
        # 保留有联系方式或至少有公司名+国家的买家（无邮箱的可用于 LinkedIn 等后续开发）
        valid_buyers = [
            b for b in unique_buyers
            if b.get("email") or b.get("website") or (b.get("company_name") and b.get("country"))
        ]

        await self._update_progress(80, f"验证后有效买家 {len(valid_buyers)} 家")

        # 不足目标数量，自动扩展关键词
        if len(valid_buyers) < target_count and not self._is_timeout():
            logger.info("结果不足，尝试扩展关键词", current=len(valid_buyers), target=target_count)
            await self._update_progress(82, "买家数量不足，正在扩展搜索关键词...")
            expanded = await self._expand_search(
                keywords, SCRAPER_REGISTRY, valid_buyers,
                target_count - len(valid_buyers), target_countries, buyer_types
            )
            if expanded:
                extra = self.deduplicator.deduplicate(expanded)
                valid_buyers.extend(extra)
                logger.info("扩展搜索完成", extra=len(extra))

        # 截取目标数量
        final_buyers = valid_buyers[:target_count]
        await self._update_progress(95, f"搜索完成，共找到 {len(final_buyers)} 家买家")
        logger.info("搜索完成", final=len(final_buyers))
        return final_buyers

    async def _run_scraper_isolated(self, source_name: str, registry: dict,
                                     keywords: list[str], countries: list[str],
                                     buyer_types: list[str]) -> list[dict]:
        """在独立任务中运行爬虫（异常隔离），一个崩了不影响其他"""
        try:
            scrape_fn = registry.get(source_name)
            if not scrape_fn:
                return []

            results = await asyncio.wait_for(
                scrape_fn(keywords, countries, buyer_types),
                timeout=180.0  # 总任务30分钟，单爬虫放宽至3分钟
            )
            return results[:settings.MAX_RESULTS_PER_SOURCE] if results else []

        except asyncio.TimeoutError:
            logger.warning("爬虫超时，跳过", source=source_name)
            return []
        except Exception as e:
            logger.error("爬虫异常，跳过", source=source_name, error=str(e))
            return []

    async def _expand_search(self, keywords: list[str], registry: dict,
                              existing: list[dict], need: int,
                              countries: list[str], buyer_types: list[str]) -> list[dict]:
        """扩展关键词搜索"""
        expanded_keywords = await kimi_client.expand_keywords(keywords, len(existing))
        if not expanded_keywords:
            return []

        all_new = []
        for source in ["google", "alibaba_rfq", "tradeindia"]:
            if self._is_timeout():
                break
            results = await self._run_scraper_isolated(
                source, registry, expanded_keywords, countries, buyer_types
            )
            all_new.extend(results)
            if len(all_new) >= need:
                break

        return all_new

    def _is_timeout(self) -> bool:
        if self._start_time is None:
            return False
        return time.time() - self._start_time > TASK_MAX_DURATION_SECONDS

    async def _update_progress(self, progress: int, message: str):
        if self.progress_callback:
            try:
                await self.progress_callback(progress, message)
            except Exception:
                pass
