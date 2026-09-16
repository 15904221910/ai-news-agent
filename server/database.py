"""数据库引擎 / 会话 / 建表。"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        path_part = url.split("sqlite:///", 1)[-1]
        if path_part and path_part != ":memory:":
            Path(path_part).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def set_database_url(url: str) -> None:
    """初始化 / 测试切换数据库。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def get_engine() -> Engine:
    if _engine is None:
        from server.config import get_settings

        set_database_url(get_settings().db_url)
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@contextlib.contextmanager
def session_scope():
    """with session_scope() as s: ... 自动 commit / rollback / close。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from server import models  # noqa: F401  确保所有模型已注册

    Base.metadata.create_all(get_engine())
    _migrate_add_columns()


def _migrate_add_columns() -> None:
    """轻量迁移：旧库（单渠道结构）重建为多选渠道结构并搬迁数据（仅 SQLite，幂等）。"""
    engine = get_engine()
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(preferences)").fetchall()
        columns = {row[1] for row in rows}
        if not columns:
            return  # 全新库（create_all 已按新结构建表）
        if "push_channels" in columns and "channel_urls" in columns:
            return  # 已是多选结构
        _rebuild_preferences_as_multi(conn, columns)
        conn.commit()


def _rebuild_preferences_as_multi(conn, columns: set[str]) -> None:  # noqa: ANN001
    """旧单渠道（push_channel/webhook_url）→ 多选（push_channels/channel_urls）。

    旧列是 NOT NULL（无法 ALTER 扩容），采用重命名-建新表-搬数据-删旧表的重建方式。
    """
    from server.users.models import Preference  # 延迟导入避免循环依赖

    url_expr = "webhook_url" if "webhook_url" in columns else "'' AS webhook_url"
    old_rows = conn.exec_driver_sql(
        "SELECT user_id, topics, keywords, exclude_keywords, push_time, "
        f"push_channel, {url_expr}, updated_at FROM preferences"
    ).fetchall()

    conn.exec_driver_sql("ALTER TABLE preferences RENAME TO preferences_legacy")
    Preference.__table__.create(conn, checkfirst=False)
    for user_id, topics, keywords, exclude_keywords, push_time, old_channel, old_url, updated_at in old_rows:
        channels, urls = _legacy_channel_to_multi(old_channel, old_url)
        conn.exec_driver_sql(
            "INSERT INTO preferences (user_id, topics, keywords, exclude_keywords, push_time, "
            "push_channels, channel_urls, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                topics or "[]",
                keywords or "",
                exclude_keywords or "",
                push_time or "08:00",
                json.dumps(channels, ensure_ascii=False),
                json.dumps(urls, ensure_ascii=False),
                updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            ),
        )
    conn.exec_driver_sql("DROP TABLE preferences_legacy")


def _legacy_channel_to_multi(channel: str | None, url: str | None) -> tuple[list[str], dict[str, str]]:
    """旧单渠道 → 多选结构：web/空 → 不推送；webhook 类地址无效则丢弃该渠道。"""
    from server.users.schemas import WEBHOOK_CHANNELS  # schemas 不依赖 database，函数内导入即可

    channel = (channel or "").strip()
    url = (url or "").strip()
    if channel in ("", "web"):
        return [], {}
    if channel == "email":
        return ["email"], {}
    if channel in WEBHOOK_CHANNELS:
        if url.startswith(("http://", "https://")):
            return [channel], {channel: url}
        return [], {}
    return [], {}
