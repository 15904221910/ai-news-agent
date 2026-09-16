"""API 全链路：偏好 CRUD / 生成流程 / 409 防重 / 悬挂清理（§16.2）。

LLM 与搜索均在测试内 mock：monkeypatch server.executor.run_agent。
"""
from __future__ import annotations

import threading
from pathlib import Path

from conftest import wait_until

from server.database import session_scope
from server.runs.models import AgentRun, ToolCall

PROFILE = {
    "name": "张三",
    "email": "a@b.com",
    "topics": ["大模型"],
    "keywords": "GPT, 具身智能",
    "exclude_keywords": "融资",
    "push_time": "09:30",
    "push_channels": [],
    "channel_urls": {},
}


# ---------- 偏好 CRUD ----------

def test_profile_get_default(client):
    resp = client.get("/api/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["id"] == 1
    assert body["preferences"]["push_time"] == "08:00"
    assert body["preferences"]["topics"] == ["大模型", "AI 芯片"]


def test_profile_put_roundtrip(client):
    resp = client.put("/api/profile", json=PROFILE)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    body = client.get("/api/profile").json()
    assert body["user"]["name"] == "张三"
    assert body["user"]["email"] == "a@b.com"
    assert body["preferences"]["topics"] == ["大模型"]
    assert body["preferences"]["push_time"] == "09:30"


def test_profile_invalid_push_time_400(client):
    resp = client.put("/api/profile", json=dict(PROFILE, push_time="25:99"))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_invalid_topic_400(client):
    resp = client.put("/api/profile", json=dict(PROFILE, topics=["不存在的话题"]))
    assert resp.status_code == 400


def test_profile_email_channel_requires_email_400(client):
    resp = client.put("/api/profile", json=dict(PROFILE, email=None, push_channels=["email"]))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_multi_channel_roundtrip(client):
    """多渠道可同时勾选：各自的地址分别保存与回读。"""
    sc = "https://sctapi.ftqq.com/SCT123.send"
    pp = "https://www.pushplus.plus/send/tok123"
    resp = client.put("/api/profile", json=dict(
        PROFILE, push_channels=["serverchan", "pushplus"],
        channel_urls={"serverchan": sc, "pushplus": pp}))
    assert resp.status_code == 200
    prefs = client.get("/api/profile").json()["preferences"]
    assert prefs["push_channels"] == ["serverchan", "pushplus"]
    assert prefs["channel_urls"] == {"serverchan": sc, "pushplus": pp}


def test_profile_webhook_channel_requires_url_400(client):
    resp = client.put("/api/profile", json=dict(PROFILE, push_channels=["feishu"]))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_multi_channel_partial_url_missing_400(client):
    """多选时任一 webhook 类渠道缺地址都要报错。"""
    resp = client.put("/api/profile", json=dict(
        PROFILE, push_channels=["wecom", "feishu"],
        channel_urls={"wecom": "https://qyapi.weixin.qq.com/hook"}))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_profile_invalid_webhook_url_400(client):
    resp = client.put("/api/profile", json=dict(
        PROFILE, push_channels=["webhook"], channel_urls={"webhook": "ftp://x"}))
    assert resp.status_code == 400


def test_profile_invalid_channel_400(client):
    resp = client.put("/api/profile", json=dict(PROFILE, push_channels=["telegram"]))
    assert resp.status_code == 400


def test_profile_empty_channels_means_web_only(client):
    """空列表 = 仅网页查看：保存成功且回读为空。"""
    resp = client.put("/api/profile", json=dict(PROFILE, push_channels=[], channel_urls={}))
    assert resp.status_code == 200
    prefs = client.get("/api/profile").json()["preferences"]
    assert prefs["push_channels"] == []
    assert prefs["channel_urls"] == {}


def test_profile_unknown_brief_and_run_404(client):
    assert client.get("/api/briefs/999").status_code == 404
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.get("/api/briefs/999").json()["error"]["code"] == "BRIEF_NOT_FOUND"


# ---------- 生成全链路 ----------

def _fake_run_agent(task, ctx, llm=None, registry=None):
    """同步版 Agent：建上下文窗口 + 写一条轨迹 + 返回简报文本。"""
    from server.agent.context_manager import ContextManager

    ctx.cm = ContextManager(ctx)
    ctx.cm.observe([{"role": "system", "content": "sys"}])
    with session_scope() as session:
        session.add(ToolCall(
            run_id=ctx.run_id, step=1, window_index=1, thought="test",
            tool_name="search_news", tool_args='{"query": "大模型"}',
            tool_result="ok", is_error=0, duration_ms=5,
        ))
    return "# 每日 AI 新闻简报 · 测试\n\n> 订阅者：张三\n\n## 大模型\n- 条目", 3


def test_generate_full_flow(client, monkeypatch, settings):
    monkeypatch.setattr("server.executor.run_agent", _fake_run_agent)

    resp = client.post("/api/briefs/generate")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "running"

    assert wait_until(
        lambda: client.get(f"/api/runs/{run_id}").json()["status"] != "running"
    ), "运行未在超时内结束"

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "success"
    assert run["steps_used"] == 3
    assert run["brief_id"] is not None

    briefs = client.get("/api/briefs").json()
    assert briefs["total"] == 1
    item = briefs["items"][0]
    assert item["id"] == run["brief_id"]
    assert item["title"].startswith("每日 AI 新闻简报")

    detail = client.get(f"/api/briefs/{run['brief_id']}").json()
    assert detail["content_md"].startswith("# 每日 AI 新闻简报")
    assert detail["run_id"] == run_id
    assert Path(detail["file_path"]).is_file()          # 简报已落盘
    assert Path(detail["file_path"]).parent == settings.workspace_dir / "briefs"

    steps = client.get(f"/api/runs/{run_id}/steps").json()
    assert len(steps["steps"]) == 1
    assert steps["steps"][0]["tool_name"] == "search_news"
    assert steps["steps"][0]["window_index"] == 1
    assert steps["windows"][0]["window_index"] == 1
    assert steps["windows"][0]["close_reason"] == "run_end"  # 运行结束归档

    runs = client.get("/api/runs").json()
    assert runs["total"] == 1
    assert runs["items"][0]["brief_id"] == run["brief_id"]


def test_generate_conflict_409(client, monkeypatch):
    gate = threading.Event()

    def blocking_run_agent(task, ctx, llm=None, registry=None):
        gate.wait(timeout=5)
        return "# 简报\n内容", 1

    monkeypatch.setattr("server.executor.run_agent", blocking_run_agent)

    first = client.post("/api/briefs/generate")
    assert first.status_code == 202
    run_id = first.json()["run_id"]

    second = client.post("/api/briefs/generate")   # 第一个仍在运行（gate 未放行）
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "RUN_IN_PROGRESS"

    gate.set()
    assert wait_until(
        lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "success"
    )


def test_generate_failure_marks_run_failed(client, monkeypatch):
    def failing_run_agent(task, ctx, llm=None, registry=None):
        raise RuntimeError("模拟 LLM 失败")

    monkeypatch.setattr("server.executor.run_agent", failing_run_agent)

    resp = client.post("/api/briefs/generate")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    assert wait_until(
        lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "failed"
    )
    run = client.get(f"/api/runs/{run_id}").json()
    assert "模拟 LLM 失败" in run["error"]
    assert client.get("/api/briefs").json()["total"] == 0


# ---------- 悬挂清理 ----------

def test_cleanup_stale_runs(db):
    from server.runs.service import cleanup_stale_runs

    with session_scope() as session:
        session.add(AgentRun(id="stale0001", user_id=1, trigger_type="scheduled", status="running"))

    assert cleanup_stale_runs() >= 1
    with session_scope() as session:
        row = session.get(AgentRun, "stale0001")
        assert row.status == "failed"
        assert "悬挂" in row.error
        assert row.finished_at is not None


# ---------- 健康检查 ----------

def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
