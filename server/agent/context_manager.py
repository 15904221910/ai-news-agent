"""上下文工程：Token 预算 + 主动硬切换 + 三层记忆（设计文档 §9.9）。

三层记忆：
- 活跃上下文：loop 的 messages 列表（唯一进入 prompt 的内容）
- Notes 交接笔记：context_windows.notes（save_notes 覆盖更新，切窗时带入新窗口）
- History 原始档案：context_windows.messages_json（整窗全量归档，search_history 按需检索）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from server.database import session_scope
from server.runs.models import ContextWindow, ToolCall

if TYPE_CHECKING:
    from server.agent.context import RunContext

ESTIMATE_DIVISOR = 2          # 字符数 / 2 ≈ token 数（保守估算，不引入 tokenizer）
FIXED_OVERHEAD_TOKENS = 2000  # 工具 schema 与固定开销


def estimate_tokens(messages: list[dict]) -> int:
    total_chars = 0
    for message in messages:
        total_chars += len(message.get("content") or "")
        for tool_call in message.get("tool_calls") or []:
            total_chars += len(json.dumps(tool_call, ensure_ascii=False, default=str))
    return total_chars // ESTIMATE_DIVISOR + FIXED_OVERHEAD_TOKENS


class ContextManager:
    def __init__(self, ctx: "RunContext") -> None:
        self.ctx = ctx
        self.window_index = 1
        self.notes = ""
        self.switch_pending = False
        self.last_used_tokens = 0
        self.last_message_count = 0
        self._last_messages: list[dict] = []
        with session_scope() as session:
            session.add(ContextWindow(run_id=ctx.run_id, window_index=1, notes=""))

    # ---------- 油量表 ----------

    def observe(self, messages: list[dict]) -> None:
        """loop 每一步调用：记录当前窗口的体量与用量。"""
        self._last_messages = messages
        self.last_used_tokens = estimate_tokens(messages)
        self.last_message_count = len(messages)

    def status(self) -> dict:
        budget = self.ctx.settings.context_budget_tokens
        used = self.last_used_tokens
        remaining = max(budget - used, 0)
        return {
            "window_index": self.window_index,
            "used_tokens": used,
            "budget_tokens": budget,
            "remaining_tokens": remaining,
            "remaining_ratio": round(remaining / budget, 3) if budget else 0.0,
            "messages_count": self.last_message_count,
            "notes_saved": bool(self.notes),
        }

    def budget_hint(self) -> dict:
        budget = self.ctx.settings.context_budget_tokens or 1
        used_pct = round(self.last_used_tokens / budget * 100)
        return {
            "role": "user",
            "content": (
                f"【系统提示】当前窗口 #{self.window_index} 上下文已用约 {used_pct}%。"
                "请先用 save_notes 保存交接笔记（若尚未保存），然后调用 new_context 切换窗口继续任务，"
                "不要尝试压缩旧对话。"
            ),
        }

    # ---------- Notes 交接笔记 ----------

    def save_notes(self, notes: str) -> None:
        self.notes = notes or ""
        with session_scope() as session:
            self._active_window(session).notes = self.notes

    # ---------- 硬切换 ----------

    def switch(self, messages: list[dict], reason: str = "model") -> list[dict]:
        """旧窗口整窗归档 → 打开新窗口（仅 system + 交接笔记 + 继续指令）。"""
        self._close_window(messages, reason)
        self.window_index += 1
        self.switch_pending = False
        self.ctx.warned = False
        with session_scope() as session:
            session.add(
                ContextWindow(run_id=self.ctx.run_id, window_index=self.window_index, notes=self.notes)
            )
        return self._new_window_messages()

    def force_switch(self, messages: list[dict]) -> list[dict]:
        """运行时硬线兜底：模型未主动切换时强制切换（笔记缺失则附加运行时骨架）。"""
        if not self.notes:
            self.notes = self._skeleton_notes()
            with session_scope() as session:
                self._active_window(session).notes = self.notes
        return self.switch(messages, reason="hard_limit")

    def close_active(self, reason: str = "run_end") -> None:
        """运行结束：归档最后一个窗口。"""
        if self._last_messages:
            self._close_window(self._last_messages, reason)

    # ---------- History 检索 ----------

    def search_history(self, keyword: str, max_hits: int = 5) -> list[dict]:
        hits: list[dict] = []
        keyword_l = (keyword or "").lower()
        if not keyword_l:
            return hits
        with session_scope() as session:
            rows = (
                session.query(ContextWindow)
                .filter(ContextWindow.run_id == self.ctx.run_id)
                .order_by(ContextWindow.window_index)
                .all()
            )
        for row in rows:
            if keyword_l in (row.notes or "").lower() and len(hits) < max_hits:
                hits.append({"window_index": row.window_index, "role": "notes",
                             "snippet": row.notes[:200]})
            text = row.messages_json or ""
            if not text:
                continue
            text_l = text.lower()
            start = 0
            while len(hits) < max_hits:
                idx = text_l.find(keyword_l, start)
                if idx < 0:
                    break
                snippet = text[max(0, idx - 60): idx + len(keyword) + 120]
                hits.append({
                    "window_index": row.window_index,
                    "role": self._guess_role(text, idx),
                    "snippet": snippet,
                })
                start = idx + len(keyword_l)
        return hits

    # ---------- 内部 ----------

    def _active_window(self, session) -> ContextWindow:
        row = (
            session.query(ContextWindow)
            .filter_by(run_id=self.ctx.run_id, window_index=self.window_index)
            .one_or_none()
        )
        if row is None:  # 容错：窗口行缺失时补建
            row = ContextWindow(run_id=self.ctx.run_id, window_index=self.window_index)
            session.add(row)
            session.flush()
        return row

    def _close_window(self, messages: list[dict], reason: str) -> None:
        payload = json.dumps(messages, ensure_ascii=False, default=str)
        with session_scope() as session:
            row = self._active_window(session)
            row.messages_json = payload
            row.message_count = len(messages)
            row.token_used = estimate_tokens(messages)
            row.close_reason = reason
            row.closed_at = datetime.now()

    def _new_window_messages(self) -> list[dict]:
        from server.agent.prompts import build_system_prompt

        notes = self.notes or "（无交接笔记：请基于当前指令重新规划，必要时用 search_history 检索档案）"
        continue_msg = (
            f"【交接笔记】\n{notes}\n\n"
            f"【继续任务】你已切换至窗口 #{self.window_index}（旧对话已归档，不再可见）。"
            "请从交接笔记中的待办继续完成任务；需要旧窗口细节时，用 search_history 检索历史档案。"
        )
        return [
            {"role": "system", "content": build_system_prompt(self.ctx)},
            {"role": "user", "content": continue_msg},
        ]

    def _skeleton_notes(self) -> str:
        with session_scope() as session:
            total = session.query(ToolCall).filter_by(run_id=self.ctx.run_id).count()
            recent = (
                session.query(ToolCall)
                .filter_by(run_id=self.ctx.run_id)
                .order_by(ToolCall.id.desc())
                .limit(3)
                .all()
            )
        recent_desc = "；".join(f"{r.tool_name}({(r.tool_args or '')[:80]})" for r in recent) or "无"
        return (
            "## 运行时状态（自动附加，可能不完整）\n"
            f"- run_id: {self.ctx.run_id}\n"
            f"- 已完成工具调用数: {total}\n"
            f"- 最近工具调用: {recent_desc}\n"
            "- 请基于已有档案继续完成任务；如需细节可检索 search_history。\n"
        )

    @staticmethod
    def _guess_role(text: str, idx: int) -> str:
        prefix = text[:idx]
        pos = prefix.rfind('"role"')
        if pos < 0:
            return "unknown"
        frag = prefix[pos: pos + 40]
        for role in ("tool", "assistant", "user", "system"):
            if f'"{role}"' in frag:
                return role
        return "unknown"
