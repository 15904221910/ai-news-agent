"""ReAct / function-calling 循环（§9.1）：LLM 自主决策 + 上下文硬切换（§9.9）。

关键点（AC-2）：代码中不存在"先搜索→再筛选→再写文件"的固定顺序；
每一步调什么完全由 llm.chat 返回的 tool_calls 决定。
"""
from __future__ import annotations

import json
import logging
import time

from server.agent.context import RunContext
from server.agent.context_manager import ContextManager
from server.agent.llm_client import LLMClient
from server.agent.prompts import build_system_prompt
from server.agent.tools import build_registry
from server.database import session_scope
from server.runs.models import ToolCall

logger = logging.getLogger(__name__)

FINAL_TOOL_NAME = "__final__"


def _save_step(
    ctx: RunContext,
    step: int,
    thought: str | None,
    tool_name: str,
    tool_args: dict,
    result: str | None,
    is_error: bool,
    duration_ms: int | None,
) -> None:
    with session_scope() as session:
        session.add(ToolCall(
            run_id=ctx.run_id,
            step=step,
            window_index=ctx.cm.window_index if ctx.cm else 1,
            thought=thought,
            tool_name=tool_name,
            tool_args=json.dumps(tool_args or {}, ensure_ascii=False),
            tool_result=result,
            is_error=1 if is_error else 0,
            duration_ms=duration_ms,
        ))


def run_agent(task: str, ctx: RunContext, llm=None, registry=None) -> tuple[str, int]:
    """执行一次 Agent 运行（LLM 自主循环），返回 (最终简报内容, 使用步数)。"""
    settings = ctx.settings
    llm = llm or LLMClient(settings)
    registry = registry or build_registry()
    ctx.cm = ctx.cm or ContextManager(ctx)

    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(ctx)},
        {"role": "user", "content": task},
    ]
    deadline = time.monotonic() + settings.run_timeout_seconds

    for step in range(1, settings.max_steps + 1):
        ctx.cm.observe(messages)

        if time.monotonic() > deadline:  # 总超时 → 兜底收敛
            logger.warning("运行总超时，强制收敛", extra={"run_id": ctx.run_id})
            return _force_final_answer(messages, ctx, llm, step), step
        if step == settings.max_steps - 1:  # 提前提醒模型收敛
            messages.append({
                "role": "user",
                "content": "注意：步数即将用尽，请立即基于已有信息输出最终简报。",
            })

        # ---- 预算门卫：油量表 → 软线提醒（每窗口一次）→ 硬线强制切窗 ----
        used = ctx.cm.last_used_tokens
        budget = settings.context_budget_tokens
        if used >= budget * settings.context_hard_limit_ratio:
            messages = ctx.cm.force_switch(messages)
            ctx.cm.observe(messages)
            logger.info("运行时强制切换窗口", extra={"run_id": ctx.run_id, "step": step})
        elif used >= budget * settings.context_soft_warn_ratio and not ctx.warned:
            messages.append(ctx.cm.budget_hint())
            ctx.warned = True

        response = llm.chat(messages, tools=registry.schemas())

        if not response.tool_calls:  # LLM 决定停止 → 最终答案
            content = (response.content or "").strip()
            if content:
                _save_step(ctx, step, content, FINAL_TOOL_NAME, {}, content[:2000], False, None)
                return content, step
            messages.append({
                "role": "user",
                "content": "你的上一条回复为空。请直接输出简报 Markdown 全文。",
            })
            continue

        # 必须保留 assistant(tool_calls) 原文，再逐个回填 tool 结果
        messages.append({
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ],
        })
        for call in response.tool_calls:  # 一次可含多个 tool_calls，按序执行
            started = time.monotonic()
            result, is_error = registry.execute_detail(call.name, call.arguments, ctx)
            duration_ms = int((time.monotonic() - started) * 1000)
            _save_step(ctx, step, response.content, call.name, call.arguments, result, is_error, duration_ms)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        if ctx.cm.switch_pending:  # 步末执行硬切换：旧窗口整窗归档 → 新窗口仅带交接笔记
            messages = ctx.cm.switch(messages, reason="model")
            logger.info("模型主动切换上下文窗口", extra={"run_id": ctx.run_id, "step": step})

    # 步数用尽 → 强制收敛
    return _force_final_answer(messages, ctx, llm, settings.max_steps), settings.max_steps


def _force_final_answer(messages: list[dict], ctx: RunContext, llm, step: int) -> str:
    hint = (
        "禁止再调用工具。请立即基于以上信息输出最佳简报（Markdown）。"
        "若信息有限，也输出当前可完成的最佳版本。"
    )
    response = llm.chat(list(messages) + [{"role": "user", "content": hint}], tools=None)
    content = (response.content or "").strip()
    if not content:
        raise RuntimeError("兜底收敛失败：模型未输出内容")
    _save_step(ctx, step, content, FINAL_TOOL_NAME, {}, content[:2000], False, None)
    return content
