"""多渠道推送单测：超长分批 / 渠道格式适配 / payload 契约 / 业务错误码 / executor 分发。

对应 server/briefs/push_channels.py（企业微信 / 飞书 / 钉钉 / Server 酱 / PushPlus / 通用 Webhook），
零外网：所有 HTTP 调用均被替换或替换 _post_webhook 本身。
"""
from __future__ import annotations

import pytest

from server.briefs import push_channels as pc


# ---------- 超长分批 ----------

def test_chunk_text_respects_byte_limit_without_loss():
    text = "\n".join("行" * 100 for _ in range(50))  # 每行 300 字节 + 换行
    chunks = pc._chunk_text(text, 3000)
    assert len(chunks) > 1
    assert all(len(c.encode("utf-8")) <= 3000 for c in chunks)
    assert "\n".join(chunks) == text  # 内容无损


def test_chunk_text_keeps_overlong_single_line_intact():
    long_line = "x" * 5000
    assert pc._chunk_text(long_line, 3800) == [long_line]  # 行边界优先，不撕行


def test_chunk_text_empty_returns_single_empty_batch():
    assert pc._chunk_text("", 100) == [""]


# ---------- 渠道格式适配 ----------

def test_adapt_wecom_removes_code_fences():
    text = "### 标题\n```python\nprint(1)\n```\n结尾"
    out = pc._adapt_markdown(text, "wecom")
    assert "```" not in out
    assert "print(1)" in out


def test_adapt_dingtalk_downgrades_all_titles():
    out = pc._adapt_markdown("# 一级\n## 二级\n### 三级", "dingtalk")
    assert out == "### 一级\n### 二级\n### 三级"


def test_adapt_feishu_converts_to_plaintext():
    text = "# 标题\n**加粗**\n[链接](https://example.com)\n> 引用\n---"
    out = pc._adapt_markdown(text, "feishu")
    assert out == "标题\n加粗\n链接\nhttps://example.com\n引用\n────────────"


def test_adapt_webhook_passthrough():
    text = "# 标题\n**加粗**"
    assert pc._adapt_markdown(text, "webhook") == text


def test_adapt_serverchan_and_pushplus_passthrough():
    text = "# 标题\n**加粗**\n- 列表"
    assert pc._adapt_markdown(text, "serverchan") == text  # 两者原生支持 Markdown
    assert pc._adapt_markdown(text, "pushplus") == text


# ---------- payload 契约 ----------

def test_build_payload_shapes():
    assert pc._build_payload("wecom", "T", "C") == {
        "msgtype": "markdown", "markdown": {"content": "C"}}
    assert pc._build_payload("dingtalk", "T", "C") == {
        "msgtype": "markdown", "markdown": {"title": "T", "text": "C"}}
    assert pc._build_payload("feishu", "T", "C") == {
        "msg_type": "text", "content": {"text": "T\n\nC"}}
    assert pc._build_payload("webhook", "T", "C") == {"title": "T", "content": "C"}
    assert pc._build_payload("serverchan", "T", "C") == {"title": "T", "desp": "C"}
    assert pc._build_payload("pushplus", "T", "C") == {
        "title": "T", "content": "C", "template": "markdown"}


def test_webhook_channel_lists_stay_consistent():
    from server.users.schemas import WEBHOOK_CHANNELS as SCHEMA_CHANNELS

    assert set(pc.WEBHOOK_CHANNELS) == set(SCHEMA_CHANNELS)  # 防止两处列表漂移


# ---------- push_brief 整体行为 ----------

def test_push_brief_rejects_unknown_channel():
    with pytest.raises(ValueError):
        pc.push_brief("telegram", "https://example.com", "内容")


def test_push_brief_single_batch_without_prefix(monkeypatch):
    sent = []
    monkeypatch.setattr(pc, "_post_webhook", lambda channel, url, payload: sent.append(payload))
    pc.push_brief("webhook", "https://example.com/hook", "# 短简报\n内容")
    assert len(sent) == 1
    assert sent[0]["content"] == "# 短简报\n内容"
    assert sent[0]["title"].startswith("AI 新闻简报 · ")


def test_push_brief_multibatch_prefix_and_sleep(monkeypatch):
    sent = []
    sleeps = []
    monkeypatch.setattr(pc, "_post_webhook", lambda channel, url, payload: sent.append(payload))
    monkeypatch.setattr(pc.time, "sleep", lambda seconds: sleeps.append(seconds))
    content = "\n".join("x" * 120 for _ in range(100))  # 约 12KB → 企业微信至少 2 批
    pc.push_brief("wecom", "https://example.com/hook", content)
    total = len(sent)
    assert total >= 2
    for index, payload in enumerate(sent, start=1):
        assert payload["markdown"]["content"].startswith(f"（第 {index}/{total} 部分）")
    assert len(sleeps) == total - 1  # 批间 sleep，最后一批不等待


# ---------- _post_webhook：HTTP 与业务错误码 ----------

class _FakeResponse:
    def __init__(self, data, status_ok=True):
        self._data = data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("HTTP 500")

    def json(self):
        if self._data is None:
            raise ValueError("no json body")
        return self._data


def test_post_webhook_raises_on_business_error(monkeypatch):
    monkeypatch.setattr(
        pc.httpx, "post", lambda *a, **k: _FakeResponse({"errcode": 93000, "errmsg": "invalid"})
    )
    with pytest.raises(RuntimeError, match="业务错误"):
        pc._post_webhook("wecom", "https://example.com", {"msgtype": "markdown"})


def test_post_webhook_accepts_zero_code_and_non_json_body(monkeypatch):
    monkeypatch.setattr(pc.httpx, "post", lambda *a, **k: _FakeResponse({"errcode": 0}))
    pc._post_webhook("wecom", "https://example.com", {})
    monkeypatch.setattr(pc.httpx, "post", lambda *a, **k: _FakeResponse(None))  # 非 JSON 响应体
    pc._post_webhook("webhook", "https://example.com", {})


def test_post_webhook_propagates_http_error(monkeypatch):
    monkeypatch.setattr(pc.httpx, "post", lambda *a, **k: _FakeResponse({}, status_ok=False))
    with pytest.raises(RuntimeError):
        pc._post_webhook("wecom", "https://example.com", {})


def test_post_webhook_pushplus_uses_200_as_success_code(monkeypatch):
    monkeypatch.setattr(
        pc.httpx, "post", lambda *a, **k: _FakeResponse({"code": 200, "msg": "请求成功"})
    )
    pc._post_webhook("pushplus", "https://www.pushplus.plus/send/token", {})  # 200 是成功码
    monkeypatch.setattr(
        pc.httpx, "post", lambda *a, **k: _FakeResponse({"code": 500, "msg": "发送失败"})
    )
    with pytest.raises(RuntimeError, match="业务错误"):
        pc._post_webhook("pushplus", "https://www.pushplus.plus/send/token", {})


def test_post_webhook_serverchan_zero_code(monkeypatch):
    monkeypatch.setattr(
        pc.httpx, "post", lambda *a, **k: _FakeResponse({"code": 0, "data": {"error": "SUCCESS"}})
    )
    pc._post_webhook("serverchan", "https://sctapi.ftqq.com/SCTxxx.send", {})
    monkeypatch.setattr(
        pc.httpx, "post", lambda *a, **k: _FakeResponse({"code": 40001, "message": "bad key"})
    )
    with pytest.raises(RuntimeError, match="业务错误"):
        pc._post_webhook("serverchan", "https://sctapi.ftqq.com/SCTxxx.send", {})


def test_is_local_url_detection():
    assert pc._is_local_url("http://127.0.0.1:9099/hook")
    assert pc._is_local_url("http://localhost/hook")
    assert pc._is_local_url("http://192.168.1.10:8080/x")
    assert pc._is_local_url("http://10.0.0.5/x")
    assert pc._is_local_url("http://172.16.3.4/x")
    assert not pc._is_local_url("http://172.32.3.4/x")
    assert not pc._is_local_url("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x")
    assert not pc._is_local_url("")


def test_post_webhook_disables_env_proxy_for_local_url(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse({"errcode": 0})

    monkeypatch.setattr(pc.httpx, "post", fake_post)
    pc._post_webhook("wecom", "http://127.0.0.1:9099/hook", {})
    assert captured["trust_env"] is False  # 本机地址绕过系统代理
    pc._post_webhook("wecom", "https://qyapi.weixin.qq.com/hook", {})
    assert captured["trust_env"] is True  # 公网地址保留系统代理


# ---------- executor._maybe_push：多渠道分发与失败隔离 ----------

def _set_channels(user_id: int, channels: list[str], urls: dict[str, str] | None = None) -> None:
    import json

    from server.database import session_scope
    from server.users.models import Preference

    with session_scope() as session:
        pref = session.get(Preference, user_id)
        pref.push_channels = json.dumps(channels)
        pref.channel_urls = json.dumps(urls or {})


def test_maybe_push_dispatches_all_selected_channels(db, monkeypatch):
    from server.executor import _maybe_push

    _set_channels(1, ["wecom", "serverchan"], {
        "wecom": "https://example.com/hook",
        "serverchan": "https://sctapi.ftqq.com/SCTxxx.send",
    })
    calls = []
    monkeypatch.setattr(
        "server.executor.push_brief",
        lambda channel, url, content: calls.append((channel, url, content)),
    )
    _maybe_push(1, "# 简报")
    assert calls == [
        ("wecom", "https://example.com/hook", "# 简报"),
        ("serverchan", "https://sctapi.ftqq.com/SCTxxx.send", "# 简报"),
    ]


def test_maybe_push_empty_channels_is_noop(db, monkeypatch):
    """未勾选任何渠道（空列表）= 仅网页查看：不触发任何外部推送。"""
    from server.executor import _maybe_push

    _set_channels(1, [])
    calls = []
    monkeypatch.setattr("server.executor.push_brief", lambda *a: calls.append(a))
    monkeypatch.setattr("server.executor.send_brief_email", lambda *a: calls.append(a))
    _maybe_push(1, "# 简报")
    assert calls == []


def test_maybe_push_single_channel_failure_isolated(db, monkeypatch):
    """多选渠道时：一个渠道失败不影响后续渠道继续推送。"""
    from server.executor import _maybe_push

    _set_channels(1, ["feishu", "serverchan"], {
        "feishu": "https://example.com/hook",
        "serverchan": "https://sctapi.ftqq.com/SCTxxx.send",
    })
    pushed = []

    def flaky(channel, url, content):
        if channel == "feishu":
            raise RuntimeError("网络错误")
        pushed.append(channel)

    monkeypatch.setattr("server.executor.push_brief", flaky)
    _maybe_push(1, "# 简报")  # 单渠道失败不抛出且不影响 serverchan
    assert pushed == ["serverchan"]
