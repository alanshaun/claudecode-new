"""
Twitter 发布器 — 浏览器自动化，不需要 API key
"""
import os
import logging
import asyncio

logger = logging.getLogger(__name__)


def post_tweet(text: str) -> str:
    return asyncio.run(_post(text))


async def _post(text: str) -> str:
    from playwright.async_api import async_playwright

    username = os.environ["TWITTER_USERNAME"]
    password = os.environ["TWITTER_PASSWORD"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()

        # 登录
        await page.goto("https://x.com/i/flow/login", wait_until="networkidle")
        await page.wait_for_selector('input[name="text"]', timeout=15000)
        await page.fill('input[name="text"]', username)
        await page.keyboard.press("Enter")

        # 可能弹出手机号验证，直接用用户名跳过
        try:
            extra = await page.wait_for_selector('input[name="text"]', timeout=4000)
            await extra.fill(username)
            await page.keyboard.press("Enter")
        except Exception:
            pass

        await page.wait_for_selector('input[name="password"]', timeout=10000)
        await page.fill('input[name="password"]', password)
        await page.keyboard.press("Enter")

        await page.wait_for_url("**/home", timeout=20000)
        logger.info("Logged in to X")

        # 发推
        await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)
        await page.click('[data-testid="tweetTextarea_0"]')
        await page.type('[data-testid="tweetTextarea_0"]', text, delay=30)

        await page.click('[data-testid="tweetButtonInline"]')
        await page.wait_for_timeout(3000)

        await browser.close()

    logger.info("Tweet posted via browser")
    return "https://x.com/home"
