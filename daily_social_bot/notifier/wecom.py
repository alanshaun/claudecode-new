"""
企业微信应用消息推送 + Access Token 管理
"""
import os
import time
import logging
import httpx

logger = logging.getLogger(__name__)

_token_cache: dict = {"token": "", "expires_at": 0}


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    corp_id = os.environ["WECOM_CORP_ID"]
    corp_secret = os.environ["WECOM_CORP_SECRET"]
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={corp_id}&corpsecret={corp_secret}"
    )
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeChat token error: {data}")

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data["expires_in"]
    return _token_cache["token"]


def send_text(text: str) -> bool:
    """向配置的成员发送文本消息"""
    token = _get_access_token()
    agent_id = int(os.environ["WECOM_AGENT_ID"])
    to_user = os.environ.get("WECOM_TO_USER", "@all")

    payload = {
        "touser": to_user,
        "msgtype": "text",
        "agentid": agent_id,
        "text": {"content": text},
    }
    resp = httpx.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    ok = data.get("errcode", -1) == 0
    if not ok:
        logger.error(f"WeChat send failed: {data}")
    return ok


def send_daily_drafts(tweets: list[str], source_title: str, source_url: str) -> bool:
    """发送今日推文草稿，要求用户回复 1/2/3 确认"""
    lines = [
        f"📰 今日素材：{source_title}",
        f"🔗 {source_url}",
        "",
        "── 请回复数字选择要发布的推文 ──",
    ]
    for i, t in enumerate(tweets, 1):
        lines.append(f"\n[{i}]\n{t}")
    lines += [
        "",
        "── 操作 ──",
        "回复 1 / 2 / 3  →  发布对应推文",
        "回复 0          →  今日跳过",
    ]
    return send_text("\n".join(lines))
