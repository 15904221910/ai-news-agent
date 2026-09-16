"""记忆工具：get_context_status / save_notes / new_context / search_history（§9.9）。

这些工具通过 ctx.cm（ContextManager）影响运行时状态：
- save_notes / search_history 立即生效；
- new_context 仅置 switch_pending，真正的窗口替换由循环在步末执行（保证消息协议完整）。
"""
from __future__ import annotations


def get_context_status(args: dict, ctx) -> dict:
    return ctx.cm.status()


def save_notes(args: dict, ctx) -> dict:
    notes = args["notes"]
    ctx.cm.save_notes(notes)
    return {"saved": True, "notes_len": len(notes)}


def new_context(args: dict, ctx) -> dict:
    notes = args.get("notes")
    if notes:
        ctx.cm.save_notes(notes)
    already_requested = ctx.cm.switch_pending
    ctx.cm.switch_pending = True
    return {
        "switched": True,
        "new_window_index": ctx.cm.window_index + 1,
        "carried_notes": bool(ctx.cm.notes),
        "note": (
            "本步已请求过切换，将在步骤结束后生效。"
            if already_requested
            else "窗口将在本步骤结束后切换，交接笔记将自动带入新窗口；请在新窗口中从待办继续任务。"
        ),
    }


def search_history(args: dict, ctx) -> dict:
    hits = ctx.cm.search_history(args["keyword"], int(args.get("max_hits", 5)))
    return {"hits": hits, "count": len(hits)}
