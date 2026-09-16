"""轻量迁移单测：旧单渠道结构（push_channel/webhook_url）→ 多选结构（push_channels/channel_urls）。"""
from __future__ import annotations

import json
import sqlite3

_LEGACY_USERS = """
    CREATE TABLE users (
        id INTEGER NOT NULL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(200),
        created_at DATETIME
    );
"""


def _read_pref(db_path):
    from server.database import session_scope
    from server.users.models import Preference

    with session_scope() as session:
        return session.get(Preference, 1)


def test_migration_rebuilds_single_channel_db(tmp_path):
    """中间代库（含 webhook_url 列）：渠道与地址搬迁进多选结构，旧列移除。"""
    from server.database import init_db, set_database_url

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        _LEGACY_USERS
        + """
        CREATE TABLE preferences (
            user_id INTEGER NOT NULL PRIMARY KEY,
            topics TEXT,
            keywords TEXT,
            exclude_keywords TEXT,
            push_time VARCHAR(5),
            push_channel VARCHAR(10) NOT NULL,
            webhook_url TEXT,
            updated_at DATETIME
        );
        INSERT INTO users (id, name) VALUES (1, '旧用户');
        INSERT INTO preferences (user_id, topics, keywords, push_time, push_channel, webhook_url)
            VALUES (1, '["大模型"]', 'GPT', '08:00', 'serverchan', 'https://sctapi.ftqq.com/SCT1.send');
        """
    )
    conn.commit()
    conn.close()

    set_database_url(f"sqlite:///{db_path.as_posix()}")
    init_db()  # create_all 跳过已存在表 → 迁移函数负责重建并搬迁

    pref = _read_pref(db_path)
    assert json.loads(pref.push_channels) == ["serverchan"]
    assert json.loads(pref.channel_urls) == {"serverchan": "https://sctapi.ftqq.com/SCT1.send"}
    assert pref.topics == '["大模型"]'  # 其他字段原样保留

    init_db()  # 再次执行应幂等，不报错也不重复迁移

    columns = {
        row[1]
        for row in sqlite3.connect(db_path).execute("PRAGMA table_info(preferences)")
    }
    assert "push_channels" in columns and "channel_urls" in columns
    assert "push_channel" not in columns  # 旧单渠道列已随重建移除


def test_migration_legacy_web_channel_becomes_empty(tmp_path):
    """极老库（无 webhook_url 列）+ web 渠道 → 迁移为空列表（仅网页查看）。"""
    from server.database import init_db, set_database_url

    db_path = tmp_path / "ancient.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        _LEGACY_USERS
        + """
        CREATE TABLE preferences (
            user_id INTEGER NOT NULL PRIMARY KEY,
            topics TEXT,
            keywords TEXT,
            exclude_keywords TEXT,
            push_time VARCHAR(5),
            push_channel VARCHAR(10) NOT NULL,
            updated_at DATETIME
        );
        INSERT INTO users (id, name) VALUES (1, '老用户');
        INSERT INTO preferences (user_id, topics, push_time, push_channel)
            VALUES (1, '[]', '08:00', 'web');
        """
    )
    conn.commit()
    conn.close()

    set_database_url(f"sqlite:///{db_path.as_posix()}")
    init_db()

    pref = _read_pref(db_path)
    assert json.loads(pref.push_channels) == []
    assert json.loads(pref.channel_urls) == {}


def test_migration_legacy_webhook_channel_without_url_is_dropped(tmp_path):
    """旧 webhook 类渠道无有效地址 → 不迁移该渠道（避免产生必然失败的配置）。"""
    from server.database import init_db, set_database_url

    db_path = tmp_path / "broken.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        _LEGACY_USERS
        + """
        CREATE TABLE preferences (
            user_id INTEGER NOT NULL PRIMARY KEY,
            topics TEXT,
            keywords TEXT,
            exclude_keywords TEXT,
            push_time VARCHAR(5),
            push_channel VARCHAR(10) NOT NULL,
            webhook_url TEXT,
            updated_at DATETIME
        );
        INSERT INTO users (id, name) VALUES (1, '坏配置用户');
        INSERT INTO preferences (user_id, topics, push_time, push_channel, webhook_url)
            VALUES (1, '[]', '08:00', 'wecom', '');
        """
    )
    conn.commit()
    conn.close()

    set_database_url(f"sqlite:///{db_path.as_posix()}")
    init_db()

    pref = _read_pref(db_path)
    assert json.loads(pref.push_channels) == []
