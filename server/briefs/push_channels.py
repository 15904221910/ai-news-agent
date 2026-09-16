"""多渠道推送（企业微信/飞书/钉钉/Server 酱/PushPlus/通用 Webhook）：格式适配 + 超长分批。

- 各渠道语法差异在 _adapt_markdown 内消化：企业微信不渲染表格/代码块，
  钉钉只渲染 ### 及以下标题，飞书 text 类型不渲染 Markdown（转纯文本）；
  Server 酱 / PushPlus 原生渲染 Markdown，原样透传；
- 超过渠道字节限制时在行边界智能分批发送（批间隔 1s 防限流）；
- 发送失败抛异常，由调用方（executor / CLI）兜底为 WARNING 日志，不影响主流程。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 15
BATCH_INTERVAL_SECONDS = 1.0

# 渠道 -> 单条消息 UTF-8 字节上限（官方限制留出余量的保守取值）
MAX_BYTES = {
    "wecom": 3800,      # 企业微信 markdown 官方 4096 字节
    "dingtalk": 18000,  # 钉钉 markdown 官方 20000 字节
    "feishu": 28000,    # 飞书官方 30KB
    "webhook": 3800,    # 通用 Webhook：保守 4KB
    "serverchan": 20000,  # Server 酱 desp 官方上限 32KB，保守 20KB
    "pushplus": 3800,     # PushPlus 免费版约 4KB，超出会转为详情页链接
}

# 渠道 -> 业务成功码集合（未列出的渠道默认 {0}；响应无 code 字段视为成功）
SUCCESS_CODES = {
    "pushplus": {200},  # PushPlus 成功码为 200 而非 0
}

WEBHOOK_CHANNELS = tuple(MAX_BYTES)


def push_brief(channel: str, webhook_url: str, content_md: str) -> None:
    """统一入口：按渠道适配内容并发送（超长自动分批）。失败抛异常。"""
    if channel not in MAX_BYTES:
        raise ValueError(f"不支持的推送渠道: {channel}")
    title = f"AI 新闻简报 · {datetime.now().strftime('%Y-%m-%d')}"
    adapted = _adapt_markdown(content_md, channel)
    batches = _chunk_text(adapted, MAX_BYTES[channel])
    total = len(batches)
    for index, batch in enumerate(batches, start=1):
        text = batch if total == 1 else f"（第 {index}/{total} 部分）\n{batch}"
        _post_webhook(channel, webhook_url, _build_payload(channel, title, text))
        if index < total:
            time.sleep(BATCH_INTERVAL_SECONDS)
    logger.info("简报推送完成", extra={"channel": channel, "batches": total})


def _adapt_markdown(text: str, channel: str) -> str:
    """按渠道渲染能力适配 Markdown 文本。"""
    text = (text or "").strip()
    if channel == "wecom":
        # 企业微信不支持代码块：去掉围栏行，内容保留
        return re.sub(r"(?m)^```[a-zA-Z0-9]*\s*$", "", text)
    if channel == "dingtalk":
        # 钉钉标题渲染以 ### 为准：所有级别统一降为三级标题，避免大号标题挤压排版
        return re.sub(r"(?m)^#{1,6}\s+", "### ", text)
    if channel == "feishu":
        return _markdown_to_plaintext(text)
    return text  # 通用 webhook / Server 酱 / PushPlus：原样透传（均支持 Markdown）


def _markdown_to_plaintext(text: str) -> str:
    """飞书 text 消息不渲染 Markdown → 转为可读纯文本。"""
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)                     # 标题标记
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)                   # 加粗
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)      # 斜体
    text = re.sub(r"`([^`\n]+)`", r"\1", text)                     # 行内代码
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1\n\2", text)   # 链接：文字与地址分两行
    text = re.sub(r"(?m)^>\s?", "", text)                          # 引用符
    text = re.sub(r"(?m)^-{3,}\s*$", "────────────", text)          # 分隔线
    return text.strip()


def _chunk_text(text: str, limit_bytes: int) -> list[str]:
    """在行边界切分，保证每批 UTF-8 字节数不超限。"""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        line_size = len(line.encode("utf-8")) + 1  # +1：换行符
        if current and size + line_size > limit_bytes:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def _build_payload(channel: str, title: str, text: str) -> dict:
    if channel == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": text}}
    if channel == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    if channel == "feishu":
        return {"msg_type": "text", "content": {"text": f"{title}\n\n{text}"}}
    if channel == "serverchan":
        return {"title": title, "desp": text}  # Server 酱：desp 字段承载正文（支持 Markdown）
    if channel == "pushplus":
        return {"title": title, "content": text, "template": "markdown"}
    return {"title": title, "content": text}  # 通用 webhook：固定 JSON 契约


def _is_local_url(url: str) -> bool:
    """本地/内网地址（webhook 指向本机或局域网服务时需绕过系统代理直连）。"""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in ("localhost", "::1") or host.startswith(("127.", "192.168.", "10.")):
        return True
    if host.startswith("172."):  # 172.16.0.0 – 172.31.255.255
        parts = host.split(".")
        return len(parts) == 4 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31
    return False


def _post_webhook(channel: str, url: str, payload: dict) -> None:
    # 内网地址绕过系统代理直连（Windows 下 httpx 会读注册表代理，否则本机/内网推送会被代理拒绝）
    response = httpx.post(
        url,
        json=payload,
        timeout=SEND_TIMEOUT_SECONDS,
        trust_env=not _is_local_url(url),
    )
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        data = {}
    # 三方平台常以 HTTP 200 + 业务错误码表示失败，必须校验业务码
    code = data.get("errcode", data.get("code", data.get("StatusCode", 0)))
    if code is not None and code not in SUCCESS_CODES.get(channel, {0}):
        raise RuntimeError(f"{channel} webhook 返回业务错误: {data}")
