"""APScheduler 定时任务（设计文档 §13）。

- BackgroundScheduler + SQLAlchemyJobStore（job 持久化，重启不丢）；
- job id `daily-{user_id}`，cron 触发器由 push_time 解析；replace_existing 幂等；
- _daily_job 为模块级函数（jobstore 按引用序列化 "server.scheduler:_daily_job"）。
"""
from __future__ import annotations

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from server.config import get_settings
from server.errors import ConflictAppError

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

MISFIRE_GRACE_SECONDS = 600


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    _scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=settings.db_url)},
        timezone=settings.app_timezone,
    )
    _scheduler.start()
    sync_all_users()
    logger.info("调度器已启动", extra={"timezone": settings.app_timezone})


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已停止")


def sync_all_users() -> None:
    """启动恢复：为所有已存在偏好的用户注册 daily job。"""
    from server.database import session_scope
    from server.users.models import Preference

    with session_scope() as session:
        items = [(row.user_id, row.push_time) for row in session.query(Preference).all()]
    for user_id, push_time in items:
        reschedule_user(user_id, push_time or "08:00")


def reschedule_user(user_id: int, push_time: str) -> None:
    """PUT /api/profile 保存后同步重排（remove+add 由 replace_existing 幂等完成）。"""
    if _scheduler is None:
        logger.warning("调度器未启动，跳过任务重排", extra={"user_id": user_id})
        return
    try:
        hour, minute = _parse_push_time(push_time)
    except ValueError:
        logger.error("push_time 非法，任务未注册", extra={"user_id": user_id, "push_time": push_time})
        return
    _scheduler.add_job(
        _daily_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        id=f"daily-{user_id}",
        args=[user_id],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
    logger.info("每日任务已注册", extra={"user_id": user_id, "push_time": push_time})


def _parse_push_time(push_time: str) -> tuple[int, int]:
    hour_s, minute_s = (push_time or "").strip().split(":", 1)
    hour, minute = int(hour_s), int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"非法时间: {push_time}")
    return hour, minute


def _daily_job(user_id: int) -> None:
    """到点触发：已有运行中则跳过本次（RECORD skipped，不排队）。"""
    from server.executor import start_run

    try:
        run_id = start_run(user_id, trigger_type="scheduled")
        logger.info("定时任务触发运行", extra={"user_id": user_id, "run_id": run_id})
    except ConflictAppError:
        logger.info("已有运行中任务，跳过本次定时触发", extra={"user_id": user_id})
