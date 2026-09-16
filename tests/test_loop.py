"""ReAct 循环：脚本化 LLM 驱动的全链路行为（§16.2）。

覆盖：正常终止 / 单步多工具 / 错误自愈 / 超步兜底 / 空回复重试 /
模型主动切窗（new_context）/ 硬线强制切窗（hard_limit）。
"""
from __future__ import annotations

from dataclasses import replace

from conftest import ScriptedLLM, text_response, tool_call_response

from server.agent.llm_client import LLMResponse
from server.agent.loop import run_agent
from server.database import session_scope
from server.runs.models import ContextWindow, ToolCall


def _steps(run_id: str) -> list[ToolCall]:
    with session_scope() as session:
        return (
            session.query(ToolCall)
            .filter_by(run_id=run_id)
            .order_by(ToolCall.id)
            .all()
        )


def _windows(run_id: str) -> list[ContextWindow]:
    with session_scope() as session:
        return (
            session.query(ContextWindow)
            .filter_by(run_id=run_id)
            .order_by(ContextWindow.window_index)
            .all()
        )


def test_normal_stop_and_persist(run_ctx, fake_registry):
    llm = ScriptedLLM([
        tool_call_response(("c1", "search_news", {"query": "大模型"})),
        text_response("# 每日 AI 新闻简报\n内容"),
    ])
    content, steps = run_agent("生成简报", run_ctx, llm=llm, registry=fake_registry)

    assert content.startswith("# 每日 AI 新闻简报")
    assert steps == 2
    rows = _steps(run_ctx.run_id)
    assert [row.tool_name for row in rows] == ["search_news", "__final__"]
    assert all(row.window_index == 1 for row in rows)
    # 第二次 chat 的输入必须保留 assistant(tool_calls) 原文并回填 tool 结果
    second_messages = llm.calls[1]["messages"]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in second_messages)
    tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["tool_call_id"] == "c1"
    assert "测试新闻" in tool_msgs[0]["content"]


def test_multi_tool_calls_in_one_step(run_ctx, fake_registry):
    llm = ScriptedLLM([
        tool_call_response(
            ("c1", "get_current_time", {}),
            ("c2", "search_news", {"query": "芯片"}),
        ),
        text_response("完成"),
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)

    assert content == "完成"
    assert steps == 2
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]  # 按序回填


def test_unknown_tool_self_heal(run_ctx, fake_registry):
    llm = ScriptedLLM([
        tool_call_response(("c1", "nonexistent_tool", {})),
        tool_call_response(("c2", "get_current_time", {})),
        text_response("自愈后完成"),
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)

    assert content == "自愈后完成"
    assert steps == 3
    rows = _steps(run_ctx.run_id)
    assert rows[0].is_error == 1
    assert "UNKNOWN_TOOL" in rows[0].tool_result
    assert rows[1].is_error == 0


def test_max_steps_forced_final(run_ctx, fake_registry):
    run_ctx.settings = replace(run_ctx.settings, max_steps=3)
    llm = ScriptedLLM([
        tool_call_response(("c1", "get_current_time", {})),
        tool_call_response(("c2", "get_current_time", {})),
        tool_call_response(("c3", "get_current_time", {})),
        text_response("超步兜底简报"),  # 第 4 次调用来自 force_final_answer
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)

    assert content == "超步兜底简报"
    assert steps == 3
    assert llm.calls[3]["tools"] is None  # 兜底收敛禁止再调工具
    rows = _steps(run_ctx.run_id)
    assert rows[-1].tool_name == "__final__"


def test_empty_final_retries(run_ctx, fake_registry):
    llm = ScriptedLLM([
        LLMResponse(content="", tool_calls=[]),   # 空回复 → 循环注入提醒后重试
        text_response("第二次输出"),
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)
    assert content == "第二次输出"
    assert steps == 2


def test_model_initiated_switch(run_ctx, fake_registry):
    llm = ScriptedLLM([
        tool_call_response(
            ("c1", "save_notes", {"notes": "## 目标\n输出简报\n## 待办\n- 继续搜索"}),
            ("c2", "new_context", {"reason": "预算不足"}),
        ),
        text_response("# 新窗口产出"),
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)

    assert content == "# 新窗口产出"
    assert steps == 2
    # 第二次 chat 的输入只有 system + 交接笔记（旧对话不进新窗口）
    second_messages = llm.calls[1]["messages"]
    assert len(second_messages) == 2
    assert second_messages[0]["role"] == "system"
    assert "交接笔记" in second_messages[1]["content"]
    assert "继续搜索" in second_messages[1]["content"]

    windows = _windows(run_ctx.run_id)
    assert [w.window_index for w in windows] == [1, 2]
    assert windows[0].close_reason == "model"
    assert "继续搜索" in windows[1].notes
    # 步内两条工具调用归属窗口 1（切换在步末生效）；final 记录在窗口 2
    rows = _steps(run_ctx.run_id)
    assert [row.window_index for row in rows] == [1, 1, 2]


def test_hard_limit_force_switch(run_ctx, fake_registry):
    run_ctx.settings = replace(
        run_ctx.settings,
        context_budget_tokens=4000,
        context_soft_warn_ratio=0.70,
        context_hard_limit_ratio=0.85,
    )
    # 让 search_news 返回长结果，使第二步开头触发硬线
    fake_registry.register(
        "search_news",
        "fake-long",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        lambda args, ctx: "长文本" * 1500,  # 4500 字符 ≈ 2250 tokens
    )
    llm = ScriptedLLM([
        tool_call_response(("c1", "search_news", {"query": "大模型"})),
        text_response("强制切窗后完成"),
    ])
    content, steps = run_agent("任务", run_ctx, llm=llm, registry=fake_registry)

    assert content == "强制切窗后完成"
    assert steps == 2
    windows = _windows(run_ctx.run_id)
    assert [w.window_index for w in windows] == [1, 2]
    assert windows[0].close_reason == "hard_limit"
    # 新窗口消息 = system + 继续指令（含运行时骨架"运行时状态"）
    second_messages = llm.calls[1]["messages"]
    assert len(second_messages) == 2
    assert "运行时状态" in second_messages[1]["content"]
    # 长工具结果不再出现在新窗口输入中（旧窗口整体归档，不压缩）
    assert all("长文本" not in (m.get("content") or "") for m in second_messages)
