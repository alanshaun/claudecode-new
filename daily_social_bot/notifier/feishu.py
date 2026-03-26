"""
飞书通知 — 发布结果卡片
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


def send_result(posted_tweet: str, tweet_url: str, other_drafts: list[str], source_title: str) -> bool:
    """发送发布结果卡片：已发内容 + 其余草稿"""
    token = _get_token()
    user_id = os.environ["FEISHU_USER_ID"]

    elements = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**素材来源：** {source_title}"},
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**已发布**\n{posted_tweet}\n\n[查看推文]({tweet_url})",
            },
        },
    ]

    if other_drafts:
        other_text = "\n\n".join(f"**草稿{i+2}**\n{d}" for i, d in enumerate(other_drafts))
        elements += [
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**其余草稿（未发布）**\n\n{other_text}"},
            },
        ]

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "推文已发布"},
            "template": "green",
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
        logger.error(f"Feishu send_result failed: {resp.text}")
    return ok


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
