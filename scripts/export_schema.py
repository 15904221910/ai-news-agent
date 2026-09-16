"""导出建表 SQL：python scripts/export_schema.py [输出路径]

从 SQLAlchemy 模型（server/*/models.py）编译 SQLite 建表语句，
默认写入 scripts/schema.sql；与服务启动时 init_db() 的 create_all 结果一致。
模型变更后重新运行本脚本即可同步 schema.sql。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from server import models  # noqa: F401  确保全部模型已注册到 metadata
from server.database import Base

HEADER = """\
-- 每日 AI 新闻助手 Agent — SQLite 建表 SQL
-- 由 SQLAlchemy 模型（server/*/models.py）编译生成，与服务启动时 init_db() 的 create_all 一致。
-- 重新生成：python scripts/export_schema.py
-- 说明：APScheduler 作业表（apscheduler_jobs）由 SQLAlchemyJobStore 首次启动时自动创建，未包含在本文件。
"""


def render_sql() -> str:
    dialect = sqlite.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scripts" / "schema.sql"
    out.write_text(render_sql(), encoding="utf-8")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
