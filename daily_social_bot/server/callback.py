"""
企业微信回调服务器 (FastAPI)
接收用户回复 1/2/3 → 触发发布流程
"""
import hashlib
import logging
import os
import struct
import time
import xml.etree.ElementTree as ET
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)

app = FastAPI()

# 全局状态：今日待发布推文列表 & 回调
_pending: dict = {
    "tweets": [],          # list[str]
    "on_confirm": None,    # callable(tweet: str)
}


def set_pending(tweets: list[str], on_confirm) -> None:
    _pending["tweets"] = tweets
    _pending["on_confirm"] = on_confirm


# ── 企业微信消息加解密 ────────────────────────────────────

def _decrypt_msg(encrypt_b64: str) -> str:
    key = b64decode(os.environ["WECOM_ENCODING_AES_KEY"] + "=")
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(key[:16]),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    raw = decryptor.update(b64decode(encrypt_b64)) + decryptor.finalize()
    # 去掉 20 字节随机串 + 4 字节长度
    msg_len = struct.unpack(">I", raw[16:20])[0]
    return raw[20:20 + msg_len].decode("utf-8")


def _verify_signature(token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
    parts = sorted([token, timestamp, nonce, encrypt])
    sha = hashlib.sha1("".join(parts).encode()).hexdigest()
    return sha == msg_signature


# ── 路由 ─────────────────────────────────────────────────

@app.get("/wecom/callback")
async def verify(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
):
    """企业微信回调 URL 验证"""
    token = os.environ["WECOM_TOKEN"]
    if _verify_signature(token, timestamp, nonce, echostr, msg_signature):
        try:
            plain = _decrypt_msg(echostr)
            return Response(content=plain, media_type="text/plain")
        except Exception:
            # 如果 echostr 不是加密内容（验证模式）直接返回
            return Response(content=echostr, media_type="text/plain")
    return Response(content="", status_code=403)


@app.post("/wecom/callback")
async def receive_message(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    request: Request,
):
    """接收用户回复"""
    body = await request.body()
    try:
        root = ET.fromstring(body.decode())
        encrypt = root.findtext("Encrypt", "")
        token = os.environ["WECOM_TOKEN"]

        if not _verify_signature(token, timestamp, nonce, encrypt, msg_signature):
            logger.warning("Invalid signature on incoming message")
            return Response(content="success")

        msg_xml = _decrypt_msg(encrypt)
        msg_root = ET.fromstring(msg_xml)
        msg_type = msg_root.findtext("MsgType", "")
        content = msg_root.findtext("Content", "").strip()

        if msg_type == "text":
            _handle_reply(content)

    except Exception as e:
        logger.error(f"Callback error: {e}")

    return Response(content="success")


def _handle_reply(content: str) -> None:
    tweets = _pending.get("tweets", [])
    on_confirm = _pending.get("on_confirm")

    if content == "0":
        logger.info("User skipped today's post")
        _pending["tweets"] = []
        _pending["on_confirm"] = None
        return

    if content in {"1", "2", "3"} and on_confirm:
        idx = int(content) - 1
        if 0 <= idx < len(tweets):
            tweet = tweets[idx]
            logger.info(f"User confirmed tweet [{content}]: {tweet[:50]}...")
            _pending["tweets"] = []
            _pending["on_confirm"] = None
            try:
                on_confirm(tweet)
            except Exception as e:
                logger.error(f"Failed to post tweet: {e}")
        else:
            logger.warning(f"Index {idx} out of range (have {len(tweets)} tweets)")
