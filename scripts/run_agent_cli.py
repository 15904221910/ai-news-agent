"""命令行直跑 Agent（不依赖 Web）：python scripts/run_agent_cli.py

用于 D2 里程碑验证与答辩兜底：真实调用 LLM 跑一次完整生成，
产出与 Web 触发一致（落 run 记录 + 简报落库/落盘 + tool_calls 轨迹）。

GitHub Actions 零成本定时部署场景（无持久 DB）可额外用环境变量直推：
PUSH_CHANNELS（逗号分隔，可多选；单值 PUSH_CHANNEL 向后兼容）/ PUSH_WEBHOOK_URL
（webhook 类渠道共用，多地址场景请用 Web 设置页）/ PUSH_EMAIL_TO + SMTP_*，
以及 EXTRA_KEYWORDS 临时补充关注关键词。
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.agent.context import RunContext  # noqa: E402
from server.agent.loop import run_agent  # noqa: E402
from server.briefs.email_sender import send_brief_email  # noqa: E402
from server.briefs.push_channels import WEBHOOK_CHANNELS, push_brief  # noqa: E402
from server.briefs.service import extract_brief_body, save_brief_result  # noqa: E402
from server.config import get_settings, validate_settings  # noqa: E402
from server.database import init_db, session_scope  # noqa: E402
from server.runs.models import AgentRun  # noqa: E402
from server.users.service import DEFAULT_USER_ID, ensure_seed_data  # noqa: E402

TASK = (
    "为用户生成今日 AI 新闻简报。请先读取用户订阅偏好，围绕关注话题与关键词多方搜索最近的 AI 新闻，"
    "筛选后按系统提示中的模板输出简报 Markdown 全文（这份输出即为最终交付物）。"
)


def build_task() -> str:
    """任务文本：EXTRA_KEYWORDS 可选（GitHub Actions 手动触发时临时补充关注点）。"""
    extra = (os.getenv("EXTRA_KEYWORDS") or "").strip()
    if extra:
        return f"{TASK}\n\n本次额外重点关注这些关键词：{extra}"
    return TASK


def push_if_configured(content_md: str) -> None:
    """无持久 DB 场景（如 GitHub Actions）按环境变量直接推送（可多选）；失败仅告警不阻断。"""
    raw = (os.getenv("PUSH_CHANNELS") or os.getenv("PUSH_CHANNEL") or "").strip()
    channels = [c.strip() for c in raw.split(",") if c.strip() and c.strip() != "web"]
    if not channels:
        return
    url = (os.getenv("PUSH_WEBHOOK_URL") or "").strip()
    for channel in channels:
        try:
            if channel == "email":
                to_addr = (os.getenv("PUSH_EMAIL_TO") or "").strip()
                if not to_addr:
                    print("跳过邮件推送：未设置 PUSH_EMAIL_TO")
                    continue
                send_brief_email(to_addr, content_md, get_settings())
            elif channel in WEBHOOK_CHANNELS:
                push_brief(channel, url, content_md)
            else:
                print(f"跳过推送：未知渠道 {channel}")
                continue
            print(f"推送完成：渠道={channel}")
        except Exception as exc:  # noqa: BLE001  单渠道失败不影响其他渠道与 run 成功状态
            print(f"推送失败（渠道 {channel}）: {type(exc).__name__}: {exc}")


def main() -> int:
    logging.basicConfig(
        level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    validate_settings(settings)
    init_db()
    ensure_seed_data()

    run_id = uuid4().hex
    with session_scope() as session:
        session.add(AgentRun(
            id=run_id, user_id=DEFAULT_USER_ID, trigger_type="manual", status="running"
        ))

    ctx = RunContext(
        run_id=run_id,
        user_id=DEFAULT_USER_ID,
        settings=settings,
        workspace_root=settings.workspace_dir,
    )
    try:
        content, steps_used = run_agent(build_task(), ctx)
        content = extract_brief_body(content)
        brief = save_brief_result(DEFAULT_USER_ID, run_id, content, settings.workspace_dir)
        with session_scope() as session:
            run = session.get(AgentRun, run_id)
            run.status = "success"
            run.steps_used = steps_used
            run.finished_at = datetime.now()
        print(f"\n运行成功：run_id={run_id} 步数={steps_used}")
        print(f"简报已保存：brief#{brief['brief_id']} -> {brief['file_path']}")
        print("\n===== 简报全文 =====\n")
        print(content)
        push_if_configured(content)
        return 0
    except Exception as exc:  # noqa: BLE001
        with session_scope() as session:
            run = session.get(AgentRun, run_id)
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now()
        print(f"\n运行失败：{type(exc).__name__}: {exc}")
        return 1
    finally:
        if ctx.cm is not None:
            ctx.cm.close_active(reason="run_end")


if __name__ == "__main__":
    raise SystemExit(main())
