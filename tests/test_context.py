"""上下文管理器：油量表 / 交接笔记 / 硬切换 / 档案检索（§16.2）。"""
from __future__ import annotations

from server.agent.context_manager import ContextManager, estimate_tokens
from server.database import session_scope
from server.runs.models import ContextWindow


def _window(run_id: str, index: int) -> ContextWindow:
    with session_scope() as session:
        return (
            session.query(ContextWindow)
            .filter_by(run_id=run_id, window_index=index)
            .one()
        )


def test_estimate_tokens():
    assert estimate_tokens([]) == 2000  # 固定开销
    messages = [{"role": "user", "content": "a" * 100}]
    assert estimate_tokens(messages) == 2000 + 50


def test_status_and_budget_hint(run_ctx):
    cm = ContextManager(run_ctx)
    messages = [
        {"role": "system", "content": "s" * 200},
        {"role": "user", "content": "u" * 200},
    ]
    cm.observe(messages)
    status = cm.status()
    assert status["window_index"] == 1
    assert status["used_tokens"] == 2000 + 200
    assert status["remaining_tokens"] == run_ctx.settings.context_budget_tokens - 2200
    assert status["messages_count"] == 2
    assert status["notes_saved"] is False

    hint = cm.budget_hint()
    assert hint["role"] == "user"
    assert "#1" in hint["content"] and "save_notes" in hint["content"]


def test_save_notes_persists(run_ctx):
    cm = ContextManager(run_ctx)
    cm.save_notes("# 笔记\n- 待办：输出简报")
    assert _window(run_ctx.run_id, 1).notes.startswith("# 笔记")


def test_switch_archives_and_carries_notes(run_ctx):
    cm = ContextManager(run_ctx)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task-1"},
    ]
    cm.observe(messages)
    cm.save_notes("## 进度\n- 已完成：第 1 轮搜索\n- 待办：整理简报")
    cm.switch_pending = True

    new_messages = cm.switch(messages, reason="model")

    assert cm.window_index == 2
    assert cm.switch_pending is False
    assert len(new_messages) == 2
    assert new_messages[0]["role"] == "system"
    assert "交接笔记" in new_messages[1]["content"]
    assert "第 1 轮搜索" in new_messages[1]["content"]
    assert all(m.get("content") != "task-1" for m in new_messages)  # 旧对话不进新窗口

    first = _window(run_ctx.run_id, 1)
    second = _window(run_ctx.run_id, 2)
    assert first.close_reason == "model"
    assert "task-1" in first.messages_json          # History 全量归档
    assert first.message_count == 2
    assert second.close_reason is None
    assert second.notes.startswith("## 进度")        # Notes 随窗口交接


def test_force_switch_uses_skeleton_notes(run_ctx):
    cm = ContextManager(run_ctx)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "t"}]
    cm.observe(messages)

    new_messages = cm.force_switch(messages)  # 无笔记 → 运行时骨架兜底

    assert cm.window_index == 2
    assert "运行时状态" in new_messages[1]["content"]
    assert "run_id" in new_messages[1]["content"]
    assert _window(run_ctx.run_id, 1).close_reason == "hard_limit"
    assert cm.notes  # 骨架笔记已落库


def test_search_history_hits_archived_window(run_ctx):
    cm = ContextManager(run_ctx)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "搜索到关键词：量子位发布新模型"},
    ]
    cm.observe(messages)
    cm.switch(messages, reason="model")

    hits = cm.search_history("量子位")
    assert hits
    assert any("量子位" in hit["snippet"] for hit in hits)
    assert all("window_index" in hit for hit in hits)


def test_close_active_archives_last_window(run_ctx):
    cm = ContextManager(run_ctx)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "t"}]
    cm.observe(messages)
    cm.close_active(reason="run_end")
    row = _window(run_ctx.run_id, 1)
    assert row.close_reason == "run_end"
    assert row.closed_at is not None
