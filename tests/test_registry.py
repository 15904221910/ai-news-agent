"""注册表执行管线：Schema 校验 / 未知工具 / 安全映射 / 异常包装 / 超时截断（§16.2）。"""
from __future__ import annotations

import time

from server.agent.tools import build_registry
from server.agent.tools import registry as registry_module


def test_unknown_tool(run_ctx):
    registry = build_registry()
    text, is_error = registry.execute_detail("no_such_tool", {}, run_ctx)
    assert is_error is True
    assert "UNKNOWN_TOOL" in text


def test_schema_validation_missing_required(run_ctx):
    registry = build_registry()
    text, is_error = registry.execute_detail("search_news", {}, run_ctx)  # 缺 query
    assert is_error is True
    assert "VALIDATION_ERROR" in text


def test_schema_validation_wrong_type(run_ctx):
    registry = build_registry()
    text, is_error = registry.execute_detail("list_dir", {"path": 123}, run_ctx)
    assert is_error is True
    assert "VALIDATION_ERROR" in text


def test_tool_exception_wrapped(run_ctx):
    registry = build_registry()

    def boom(args, ctx):
        raise RuntimeError("boom")

    registry.register("boom_tool", "x", {"type": "object", "properties": {}}, boom)
    text, is_error = registry.execute_detail("boom_tool", {}, run_ctx)
    assert is_error is True
    assert "TOOL_ERROR" in text and "boom" in text


def test_security_denied_mapping(run_ctx):
    registry = build_registry()
    text, is_error = registry.execute_detail("read_file", {"path": "../.env"}, run_ctx)
    assert is_error is True
    assert "SECURITY_DENIED" in text


def test_tool_timeout_wrapped(run_ctx, monkeypatch):
    registry = build_registry()
    monkeypatch.setattr(registry_module, "TOOL_TIMEOUT_SECONDS", 0.2)

    def slow(args, ctx):
        time.sleep(1.5)
        return "done"

    registry.register("slow_tool", "x", {"type": "object", "properties": {}}, slow)
    text, is_error = registry.execute_detail("slow_tool", {}, run_ctx)
    assert is_error is True
    assert "TOOL_TIMEOUT" in text


def test_result_truncation(run_ctx):
    registry = build_registry()
    registry.register(
        "big_tool", "x", {"type": "object", "properties": {}}, lambda args, ctx: "y" * 5000
    )
    text, is_error = registry.execute_detail("big_tool", {}, run_ctx)
    assert is_error is False
    assert len(text) < 5000
    assert "truncated" in text


def test_registry_exposes_12_tools(run_ctx):
    registry = build_registry()
    names = registry.tool_names()
    assert len(names) == 12
    for required in ("list_dir", "read_file", "search_content", "write_file", "bash",
                     "search_news", "get_user_profile", "get_current_time",
                     "get_context_status", "save_notes", "new_context", "search_history"):
        assert required in names
    assert all(item["type"] == "function" for item in registry.schemas())
