"""运行记录接口：状态轮询 / 列表 / 轨迹 / 窗口档案。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from server.runs.schemas import RunListOut, RunOut, RunStepsOut, WindowArchiveOut
from server.runs.service import get_run, get_run_steps, get_window_archive, list_runs
from server.users.service import DEFAULT_USER_ID

router = APIRouter(tags=["runs"])


@router.get("/api/runs/{run_id}/steps", response_model=RunStepsOut)
def run_steps(run_id: str) -> dict:
    return get_run_steps(run_id)


@router.get("/api/runs/{run_id}/windows/{window_index}", response_model=WindowArchiveOut)
def run_window_archive(run_id: str, window_index: int) -> dict:
    return get_window_archive(run_id, window_index)


@router.get("/api/runs/{run_id}", response_model=RunOut)
def run_detail(run_id: str) -> dict:
    return get_run(run_id)


@router.get("/api/runs", response_model=RunListOut)
def run_list(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
) -> dict:
    return list_runs(DEFAULT_USER_ID, page=page, size=size)
