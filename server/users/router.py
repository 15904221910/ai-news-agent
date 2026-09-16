"""用户接口：GET/PUT /api/profile。"""
from __future__ import annotations

from fastapi import APIRouter

from server.users.schemas import ProfileIn
from server.users.service import DEFAULT_USER_ID, get_profile, upsert_profile

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("")
def read_profile() -> dict:
    return get_profile(DEFAULT_USER_ID)


@router.put("")
def save_profile(payload: ProfileIn) -> dict:
    profile = upsert_profile(DEFAULT_USER_ID, payload)
    # 保存后同步重排定时任务（调度器未启动时内部仅记日志，不影响保存结果）
    from server.scheduler import reschedule_user

    reschedule_user(DEFAULT_USER_ID, payload.push_time)
    return {"ok": True, "profile": profile}
