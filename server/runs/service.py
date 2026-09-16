"""运行记录服务：状态 / ReAct 轨迹 / 窗口档案 / 悬挂清理。"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from server.briefs.models import Brief
from server.database import session_scope
from server.errors import NotFoundAppError
from server.runs.models import AgentRun, ContextWindow, ToolCall

logger = logging.getLogger(__name__)


def get_run(run_id: str) -> dict:
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise NotFoundAppError(f"运行记录不存在: {run_id}", code="RUN_NOT_FOUND")
        brief = session.query(Brief).filter(Brief.run_id == run_id).first()
        return {
            "id": run.id,
            "user_id": run.user_id,
            "trigger_type": run.trigger_type,
            "status": run.status,
            "steps_used": run.steps_used or 0,
            "error": run.error,
            "brief_id": brief.id if brief else None,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
        }


def list_runs(user_id: int, page: int = 1, size: int = 20) -> dict:
    with session_scope() as session:
        query = session.query(AgentRun).filter(AgentRun.user_id == user_id)
        total = query.count()
        rows = (
            query.order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        items = [
            {
                "id": run.id,
                "user_id": run.user_id,
                "trigger_type": run.trigger_type,
                "status": run.status,
                "steps_used": run.steps_used or 0,
                "error": run.error,
                "brief_id": None,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
            }
            for run in rows
        ]
        # 附 brief_id 映射（避免 N+1：一次查全）
        run_ids = [run.id for run in rows]
        brief_map = {}
        if run_ids:
            for brief in session.query(Brief).filter(Brief.run_id.in_(run_ids)).all():
                brief_map[brief.run_id] = brief.id
        for item in items:
            item["brief_id"] = brief_map.get(item["id"])
    return {"total": total, "page": page, "size": size, "items": items}


def get_run_steps(run_id: str) -> dict:
    """轨迹 API 数据源：steps（含 window_index）+ windows 摘要（含 close_reason 与交接笔记）。"""
    with session_scope() as session:
        if session.get(AgentRun, run_id) is None:
            raise NotFoundAppError(f"运行记录不存在: {run_id}", code="RUN_NOT_FOUND")
        step_rows = (
            session.query(ToolCall)
            .filter(ToolCall.run_id == run_id)
            .order_by(ToolCall.step, ToolCall.id)
            .all()
        )
        window_rows = (
            session.query(ContextWindow)
            .filter(ContextWindow.run_id == run_id)
            .order_by(ContextWindow.window_index)
            .all()
        )
        steps = [
            {
                "step": row.step,
                "window_index": row.window_index or 1,
                "thought": row.thought,
                "tool_name": row.tool_name,
                "tool_args": _loads(row.tool_args),
                "tool_result": row.tool_result,
                "is_error": bool(row.is_error),
                "duration_ms": row.duration_ms,
                "created_at": _iso(row.created_at),
            }
            for row in step_rows
        ]
        windows = [
            {
                "window_index": row.window_index,
                "close_reason": row.close_reason,
                "notes": row.notes,
                "message_count": row.message_count,
                "token_used": row.token_used,
                "opened_at": _iso(row.opened_at),
                "closed_at": _iso(row.closed_at),
            }
            for row in window_rows
        ]
    return {"run_id": run_id, "steps": steps, "windows": windows}


def get_window_archive(run_id: str, window_index: int) -> dict:
    """[P1] History 可视化：查看某窗口全量原始消息。"""
    with session_scope() as session:
        row = (
            session.query(ContextWindow)
            .filter_by(run_id=run_id, window_index=window_index)
            .one_or_none()
        )
        if row is None:
            raise NotFoundAppError(
                f"窗口不存在: run={run_id} window={window_index}", code="CONTEXT_WINDOW_NOT_FOUND"
            )
        try:
            messages = json.loads(row.messages_json) if row.messages_json else []
        except json.JSONDecodeError:
            messages = []
        return {
            "run_id": run_id,
            "window_index": row.window_index,
            "close_reason": row.close_reason,
            "notes": row.notes,
            "message_count": row.message_count,
            "token_used": row.token_used,
            "messages": messages,
        }


def cleanup_stale_runs() -> int:
    """启动时清理悬挂 running（进程崩溃/重启遗留），返回清理条数。"""
    with session_scope() as session:
        rows = session.query(AgentRun).filter(AgentRun.status == "running").all()
        for run in rows:
            run.status = "failed"
            run.error = "进程重启，悬挂运行已清理"
            run.finished_at = datetime.now()
        return len(rows)


def _loads(text: str | None) -> dict:
    try:
        value = json.loads(text) if text else {}
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
