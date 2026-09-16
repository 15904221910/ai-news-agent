"""简报接口：生成 / 列表 / 详情。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from server.briefs.service import get_brief, list_briefs
from server.executor import start_run
from server.users.service import DEFAULT_USER_ID

router = APIRouter(tags=["briefs"])


@router.post("/api/briefs/generate", status_code=202)
def generate_brief() -> dict:
    """手动触发生成：异步执行，立即返回 run_id（前端每 2s 轮询 /api/runs/{run_id}）。"""
    run_id = start_run(DEFAULT_USER_ID, trigger_type="manual")
    return {"run_id": run_id, "status": "running"}


@router.get("/api/briefs")
def brief_list(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
) -> dict:
    return list_briefs(DEFAULT_USER_ID, page=page, size=size)


@router.get("/api/briefs/{brief_id}")
def brief_detail(brief_id: int) -> dict:
    return get_brief(brief_id)
