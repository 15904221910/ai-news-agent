"""简报服务：保存生成结果 / 列表 / 详情。"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from server.briefs.models import Brief
from server.database import session_scope
from server.errors import NotFoundAppError

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def save_brief_result(
    user_id: int, run_id: str, content_md: str, workspace_root: Path
) -> dict:
    """运行成功后落盘 + 落库；返回 brief 摘要信息。

    文件命名 {date}-{run_id[:8]}.md：同日多次运行不互相覆盖（模型自写的 {date}.md 保留为草稿）。
    """
    now = datetime.now()
    brief_date = now.date()
    title = _extract_title(content_md, brief_date)

    briefs_dir = Path(workspace_root) / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    file_path = briefs_dir / f"{brief_date.isoformat()}-{run_id[:8]}.md"
    file_path.write_text(content_md, encoding="utf-8")

    with session_scope() as session:
        brief = Brief(
            user_id=user_id,
            run_id=run_id,
            title=title,
            brief_date=brief_date,
            content_md=content_md,
            file_path=file_path.as_posix(),
            pushed_at=now,  # web 渠道生成即可见；email 渠道失败也不回退（FR-U3）
        )
        session.add(brief)
        session.flush()
        brief_id = brief.id
    return {
        "brief_id": brief_id,
        "title": title,
        "brief_date": brief_date.isoformat(),
        "file_path": file_path.as_posix(),
    }


def list_briefs(user_id: int, page: int = 1, size: int = 20) -> dict:
    with session_scope() as session:
        query = session.query(Brief).filter(Brief.user_id == user_id)
        total = query.count()
        rows = (
            query.order_by(Brief.brief_date.desc(), Brief.id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        items = [
            {
                "id": row.id,
                "title": row.title,
                "brief_date": row.brief_date.isoformat() if row.brief_date else None,
                "pushed_at": _iso(row.pushed_at),
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]
    return {"total": total, "page": page, "size": size, "items": items}


def get_brief(brief_id: int) -> dict:
    with session_scope() as session:
        row = session.get(Brief, brief_id)
        if row is None:
            raise NotFoundAppError(f"简报不存在: {brief_id}", code="BRIEF_NOT_FOUND")
        return {
            "id": row.id,
            "user_id": row.user_id,
            "run_id": row.run_id,
            "title": row.title,
            "brief_date": row.brief_date.isoformat() if row.brief_date else None,
            "content_md": row.content_md,
            "file_path": row.file_path,
            "pushed_at": _iso(row.pushed_at),
            "created_at": _iso(row.created_at),
        }


def extract_brief_body(content_md: str) -> str:
    """剥离简报正文之前的前言（模型偶尔会加"以下是全文交付物"之类），从首个一级标题开始。"""
    text = (content_md or "").lstrip()
    match = _TITLE_RE.search(text)
    if match is None:
        return text.strip()
    return text[match.start():].strip()


def _extract_title(content_md: str, brief_date) -> str:
    match = _TITLE_RE.search(content_md or "")
    if match:
        return match.group(1)[:200]
    return f"AI 新闻简报 · {brief_date.isoformat()}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
