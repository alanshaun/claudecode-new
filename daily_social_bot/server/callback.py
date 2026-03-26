"""
Render 上的 FastAPI 服务
职责：接收飞书按钮回调 → 从 value 中取出推文正文 → 发布到 X
"""
import hashlib
import hmac
import json
import logging
import os

import httpx
from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)
app = FastAPI()


def _post_tweet(text: str) -> str:
    """返回发布后的推文 URL"""
    import tweepy
    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )
    resp = client.create_tweet(text=text)
    tweet_id = resp.data["id"]
    return f"https://x.com/i/status/{tweet_id}"


def _notify_feishu(text: str):
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    user_id = os.environ.get("FEISHU_USER_ID", "")
    if not all([app_id, app_secret, user_id]):
        return
    try:
        token_resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        token = token_resp.json()["tenant_access_token"]
        httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": user_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Feishu notify failed: {e}")


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/feishu/callback")
async def feishu_callback(request: Request):
    body = await request.json()

    # URL 验证握手
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # 兼容两种飞书回调格式
    value = (
        body.get("action", {}).get("value")
        or body.get("event", {}).get("action", {}).get("value")
        or {}
    )

    action = value.get("action", "")

    if action == "skip":
        logger.info("User skipped today's post")
        _notify_feishu("⏭️ 已跳过今日推文")
        return {"toast": {"type": "info", "content": "已跳过"}}

    if action == "post_tweet":
        tweet = value.get("tweet", "")
        if not tweet:
            return {"toast": {"type": "error", "content": "推文内容为空"}}
        try:
            url = _post_tweet(tweet)
            logger.info(f"Tweet posted: {url}")
            _notify_feishu(f"✅ 推文已发布！\n{url}\n\n内容：{tweet}")
            return {"toast": {"type": "success", "content": "推文已发布！"}}
        except Exception as e:
            logger.error(f"Post failed: {e}")
            _notify_feishu(f"❌ 发布失败：{e}")
            return {"toast": {"type": "error", "content": f"发布失败：{e}"}}

    return Response(content="ok")
