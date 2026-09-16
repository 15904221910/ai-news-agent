"""运行记录响应模型（供 OpenAPI 文档与序列化约定）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunOut(BaseModel):
    id: str
    user_id: int
    trigger_type: str
    status: str
    steps_used: int
    error: str | None = None
    brief_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunListOut(BaseModel):
    total: int
    page: int
    size: int
    items: list[RunOut]


class StepOut(BaseModel):
    step: int
    window_index: int
    thought: str | None = None
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: str | None = None
    is_error: bool = False
    duration_ms: int | None = None
    created_at: str | None = None


class WindowOut(BaseModel):
    window_index: int
    close_reason: str | None = None
    notes: str | None = None
    message_count: int | None = None
    token_used: int | None = None
    opened_at: str | None = None
    closed_at: str | None = None


class RunStepsOut(BaseModel):
    run_id: str
    steps: list[StepOut]
    windows: list[WindowOut]


class WindowArchiveOut(BaseModel):
    run_id: str
    window_index: int
    close_reason: str | None = None
    notes: str | None = None
    message_count: int | None = None
    token_used: int | None = None
    messages: list[dict[str, Any]]
