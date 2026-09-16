"""Agent 运行执行器：全局互斥锁 + 后台线程（设计文档 §12.1）。

- 全局单运行：非阻塞抢锁失败 → 409 RUN_IN_PROGRESS（手动/定时共用同一把锁）；
- 线程内跑 run_agent，成功落 Brief + 文件，失败落 run.error；
- finally 归档最后窗口（三层记忆收尾）并释放锁。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from uuid import uuid4

from server.agent.context import RunContext
from server.agent.loop import run_agent
from server.briefs.email_sender import send_brief_email
from server.briefs.push_channels import WEBHOOK_CHANNELS, push_brief
from server.briefs.service import extract_brief_body, save_brief_result
from server.config import get_settings
from server.database import session_scope
from server.errors import ConflictAppError
from server.runs.models import AgentRun
from server.users.models import Preference, User

logger = logging.getLogger(__name__)

_run_lock = threading.Lock()  # 全局单运行锁：手动与定时任务互斥


def start_run(user_id: int, trigger_type: str = "manual") -> str:
    """抢锁 + 建 running 记录 + 启动后台线程；返回 run_id。锁由后台线程释放。"""
    if not _run_lock.acquire(blocking=False):
        raise ConflictAppError("已有 Agent 任务正在运行，请稍后再试", code="RUN_IN_PROGRESS")

    settings = get_settings()
    run_id = uuid4().hex
    try:
        with session_scope() as session:
            session.add(AgentRun(
                id=run_id, user_id=user_id, trigger_type=trigger_type, status="running"
            ))
    except Exception:
        _run_lock.release()
        raise

    threading.Thread(
        target=_execute,
        args=(run_id, user_id),
        name=f"agent-run-{run_id[:8]}",
        daemon=True,
    ).start()
    logger.info("Agent 运行已启动", extra={"run_id": run_id, "trigger": trigger_type})
    return run_id


def is_running() -> bool:
    return _run_lock.locked()


def _build_task(user_id: int) -> str:
    return (
        "为用户生成今日 AI 新闻简报。请先读取用户订阅偏好，围绕关注话题与关键词多方搜索最近的 AI 新闻，"
        "筛选后按系统提示中的模板输出简报 Markdown 全文（这份输出即为最终交付物）。"
    )


def _execute(run_id: str, user_id: int) -> None:
    settings = get_settings()
    ctx: RunContext | None = None
    try:
        ctx = RunContext(
            run_id=run_id,
            user_id=user_id,
            settings=settings,
            workspace_root=settings.workspace_dir,
        )
        content, steps_used = run_agent(_build_task(user_id), ctx)
        content = extract_brief_body(content)
        brief = save_brief_result(
            user_id=user_id,
            run_id=run_id,
            content_md=content,
            workspace_root=settings.workspace_dir,
        )
        _finish_run(run_id, status="success", steps_used=steps_used)
        _maybe_push(user_id, content)
        logger.info(
            "Agent 运行成功",
            extra={"run_id": run_id, "steps_used": steps_used, "brief_id": brief["brief_id"]},
        )
    except Exception as exc:  # noqa: BLE001 任何失败都落库，不让线程静默崩溃
        logger.exception("Agent 运行失败", extra={"run_id": run_id})
        _finish_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        if ctx is not None and ctx.cm is not None:
            try:
                ctx.cm.close_active(reason="run_end")
            except Exception:  # noqa: BLE001 归档失败不影响运行结果
                logger.exception("归档最后窗口失败", extra={"run_id": run_id})
        _run_lock.release()


def _finish_run(
    run_id: str, status: str, steps_used: int | None = None, error: str | None = None
) -> None:
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            logger.error("运行记录不存在，无法更新状态", extra={"run_id": run_id})
            return
        run.status = status
        if steps_used is not None:
            run.steps_used = steps_used
        run.error = error
        run.finished_at = datetime.now()


def _maybe_push(user_id: int, content_md: str) -> None:
    """按偏好渠道逐个推送简报（可多选）：单渠道失败仅记日志，不影响其他渠道与 run 状态。"""
    with session_scope() as session:
        pref = session.get(Preference, user_id)
        user = session.get(User, user_id)
        if pref is None:
            return
        channels = _json_load(pref.push_channels, [])
        urls = _json_load(pref.channel_urls, {})
        email = user.email if user else None

    if not channels:
        return  # 未选任何渠道：仅网页查看
    pushed: list[str] = []
    for channel in channels:
        try:
            if channel == "email":
                if not email:
                    raise RuntimeError("缺少邮箱")
                send_brief_email(email, content_md, get_settings())
            elif channel in WEBHOOK_CHANNELS:
                url = urls.get(channel, "")
                if not url:
                    raise RuntimeError("缺少推送地址")
                push_brief(channel, url, content_md)
            else:
                logger.warning("未知推送渠道，跳过", extra={"user_id": user_id, "channel": channel})
                continue
            pushed.append(channel)
        except Exception as exc:  # noqa: BLE001 单渠道失败不影响其他渠道
            logger.warning(
                "简报推送失败（渠道 %s）: %s", channel, exc, extra={"user_id": user_id}
            )
    if pushed:
        logger.info("简报已推送", extra={"user_id": user_id, "channels": pushed})


def _json_load(raw: str | None, fallback):  # noqa: ANN001
    try:
        value = json.loads(raw) if raw else fallback
    except json.JSONDecodeError:
        return fallback
    return value if isinstance(value, type(fallback)) else fallback
