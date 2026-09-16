"""种子数据（幂等）：python scripts/seed.py

创建默认用户 user_id=1 与默认订阅偏好；已存在则跳过。
Web 启动时（main lifespan）也会自动执行同样逻辑，此脚本用于单独建库/演示。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import get_settings  # noqa: E402
from server.database import init_db  # noqa: E402
from server.users.service import ensure_seed_data  # noqa: E402


def main() -> int:
    settings = get_settings()
    print(f"数据库: {settings.db_url}")
    init_db()
    ensure_seed_data()
    print("种子数据就绪（幂等，可重复执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
