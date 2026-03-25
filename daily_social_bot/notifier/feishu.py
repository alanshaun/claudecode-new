"""
飞书通知 — 交互卡片，推文内容直接嵌入按钮 value（无服务器状态）
"""
import json
import os
import time
import logging
import httpx

logger = logging.getLogger(__name__)
FEISHU_API = "https://open.feishu.cn/open-apis"
_token_cache: dict = {"token": "", "expires_at": 0}


def _get_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = httpx.post(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        json={"app_id": os.environ["FEISHU_APP_ID"], "app_secret": os.environ["FEISHU_APP_SECRET"]},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data["expire"]
    return _token_cache["token"]


def send_text(text: str) -> bool:
    token = _get_token()
    user_id = os.environ["FEISHU_USER_ID"]
    resp = httpx.post(
        f"{FEISHU_API}/im/v1/messages?receive_id_type=open_id",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
        timeout=10,
    )
    ok = resp.status_code == 200 and resp.json().get("code") == 0
    if not ok:
        logger.error(f"Feishu send_text failed: {resp.text}")
    return ok


def send_daily_drafts(tweets: list[str], source_title: str, source_url: str) -> bool:
    """
    发送交互卡片。
    每个按钮的 value 直接携带推文正文，Render 收到回调后无需查库即可发推。
    """
    token = _get_token()
    user_id = os.environ["FEISHU_USER_ID"]

    # 构建卡片元素
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📰 今日素材**\n{source_title}\n[查看原文]({source_url})",
            },
        },
        {"tag": "hr"},
    ]

    for i, tweet in enumerate(tweets, 1):
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**[{i}]**\n{tweet}"},
        })

    # 按钮行：每条推文一个按钮 + 跳过
    actions = []
    for i, tweet in enumerate(tweets, 1):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"发布第 {i} 条"},
            "type": "primary",
            # 推文正文直接放在 value 里，Render 回调时取出直接发推
            "value": {"action": "post_tweet", "tweet": tweet},
        })
    actions.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "今日跳过"},
        "type": "danger",
        "value": {"action": "skip"},
    })

    elements.append({"tag": "hr"})
    elements.append({"tag": "action", "actions": actions})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "每日推文 — 请选择发布"},
            "template": "blue",
        },
        "elements": elements,
    }

    resp = httpx.post(
        f"{FEISHU_API}/im/v1/messages?receive_id_type=open_id",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "receive_id": user_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        },
        timeout=10,
    )
    ok = resp.status_code == 200 and resp.json().get("code") == 0
    if not ok:
        logger.error(f"Feishu send_card failed: {resp.text}")
    return ok
