"""
飞书回调服务器 (FastAPI)
接收用户点击交互卡片按钮的事件 → 触发发布
"""
import hashlib
import json
import logging
import os

from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)
app = FastAPI()

_pending: dict = {
    "tweets": [],
    "on_confirm": None,
}


def set_pending(tweets: list[str], on_confirm) -> None:
    _pending["tweets"] = tweets
    _pending["on_confirm"] = on_confirm


@app.post("/feishu/callback")
async def feishu_callback(request: Request):
    body = await request.json()

    # 飞书 URL 验证握手
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    event = body.get("event", {})
    action = event.get("action", {})
    value = action.get("value", {})

    if not value:
        # 兼容卡片回调格式
        action = body.get("action", {})
        value = action.get("value", {})

    if not value:
        return Response(content="ok")

    act = value.get("action", "")
    if act == "skip":
        logger.info("User skipped today's post")
        _pending["tweets"] = []
        _pending["on_confirm"] = None
        return {"toast": {"type": "info", "content": "已跳过今日推文"}}

    if act == "post_tweet":
        idx = int(value.get("index", "1")) - 1
        tweets = _pending.get("tweets", [])
        on_confirm = _pending.get("on_confirm")
        if on_confirm and 0 <= idx < len(tweets):
            tweet = tweets[idx]
            logger.info(f"User confirmed tweet [{idx+1}]")
            _pending["tweets"] = []
            _pending["on_confirm"] = None
            try:
                on_confirm(tweet)
                return {"toast": {"type": "success", "content": "推文已发布！"}}
            except Exception as e:
                logger.error(f"Post failed: {e}")
                return {"toast": {"type": "error", "content": f"发布失败：{e}"}}

    return Response(content="ok")
