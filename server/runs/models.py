"""Agent 运行 / 工具调用 / 上下文窗口 ORM 模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4.hex
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(10), default="manual")  # manual | scheduled
    status: Mapped[str] = mapped_column(String(10), default="running")       # running | success | failed
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    window_index: Mapped[int] = mapped_column(Integer, default=1)
    thought: Mapped[str | None] = mapped_column(Text)      # 该步 LLM 文本输出（可空）
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_args: Mapped[str] = mapped_column(Text, default="{}")  # JSON 字符串
    tool_result: Mapped[str | None] = mapped_column(Text)  # 截断后结果
    is_error: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ContextWindow(Base):
    """三层记忆的 Notes + History 归档（§9.9）。"""

    __tablename__ = "context_windows"
    __table_args__ = (UniqueConstraint("run_id", "window_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")   # 交接笔记（save_notes 覆盖更新）
    messages_json: Mapped[str | None] = mapped_column(Text)  # 窗口关闭时写入全量消息（History）
    message_count: Mapped[int | None] = mapped_column(Integer)
    token_used: Mapped[int | None] = mapped_column(Integer)
    close_reason: Mapped[str | None] = mapped_column(String(12))  # model | hard_limit | run_end
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
