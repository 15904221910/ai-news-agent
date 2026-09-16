"""pytest 公共 fixtures：临时沙箱 / 独立 DB / 注入 Settings / 脚本化 LLM / TestClient。

原则：测试零外网依赖——LLM 用 ScriptedLLM，search_news 用 fake_registry 替换。
"""
from __future__ import annotations

import copy
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from server.agent.llm_client import LLMResponse, ToolCallRequest


# ---------- 脚本化 LLM ----------

class ScriptedLLM:
    """按脚本队列依次返回 LLMResponse；记录每次 chat 的 messages/tools 快照。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=None, max_tokens=None) -> LLMResponse:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        if not self.responses:
            raise AssertionError("ScriptedLLM 脚本已耗尽，但循环仍在请求 LLM")
        return self.responses.pop(0)


def tool_call_response(*calls: tuple[str, str, dict]) -> LLMResponse:
    """tool_call_response(("id1", "search_news", {"query": "x"}), ...)"""
    return LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id=cid, name=name, arguments=args) for cid, name, args in calls],
    )


def text_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=[])


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------- 基础 fixtures ----------

@pytest.fixture()
def settings(tmp_path):
    """注入测试 Settings：独立 DB 文件 + 临时 workspace 沙箱。"""
    from server.config import load_settings, set_settings

    value = replace(
        load_settings(),
        db_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        workspace_dir=tmp_path / "ws",
        llm_api_key="sk-test",
    )
    set_settings(value)
    return value


@pytest.fixture()
def db(settings):
    """独立数据库 + 种子数据（user_id=1，满足外键）。"""
    from server.database import init_db, set_database_url
    from server.users.service import ensure_seed_data

    set_database_url(settings.db_url)
    init_db()
    ensure_seed_data()
    return settings


@pytest.fixture()
def run_ctx(db):
    """带 AgentRun 记录的 RunContext（tool_calls 外键需要）。"""
    from server.agent.context import RunContext
    from server.database import session_scope
    from server.runs.models import AgentRun

    run_id = uuid4().hex
    with session_scope() as session:
        session.add(AgentRun(id=run_id, user_id=1, trigger_type="manual", status="running"))
    return RunContext(
        run_id=run_id,
        user_id=1,
        settings=db,
        workspace_root=db.workspace_dir,
    )


@pytest.fixture()
def fake_registry():
    """把 search_news 替换为假实现的完整注册表（12 工具，零外网）。"""
    from server.agent.tools import build_registry

    registry = build_registry()
    registry.register(
        "search_news",
        "fake search_news（测试用）",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "days": {"type": "integer"},
            },
            "required": ["query"],
        },
        lambda args, ctx: {
            "items": [
                {
                    "title": "测试新闻",
                    "url": "https://example.com/a",
                    "source": "测试源",
                    "published_at": "2026-09-16T08:00:00+08:00",
                    "snippet": "snippet-" + args["query"],
                }
            ],
            "provider": "fake",
        },
    )
    return registry


@pytest.fixture()
def client(db, monkeypatch):
    """TestClient：禁用真实调度器；500 不抛出以便断言统一错误 JSON。"""
    monkeypatch.setattr("server.main.start_scheduler", lambda: None)
    monkeypatch.setattr("server.main.shutdown_scheduler", lambda: None)

    from fastapi.testclient import TestClient

    from server.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
