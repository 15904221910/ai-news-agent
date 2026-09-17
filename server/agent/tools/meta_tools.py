"""基础元工具：get_user_profile / get_current_time。"""
from __future__ import annotations

import json
from datetime import datetime

from server.database import session_scope
from server.users.models import Preference, User

_WEEKDAYS = "一二三四五六日"


def get_user_profile(args: dict, ctx) -> dict:
    """读取当前用户订阅偏好（user_id 由运行时注入，不暴露给 LLM）。"""
    with session_scope() as session:
        user = session.get(User, ctx.user_id)
        if user is None:
            raise ValueError(f"用户不存在: {ctx.user_id}")
        pref = session.get(Preference, ctx.user_id)
        try:
            topics = json.loads(pref.topics) if pref and pref.topics else []
        except json.JSONDecodeError:
            topics = []
        try:
            channels = json.loads(pref.push_channels) if pref and pref.push_channels else []
        except json.JSONDecodeError:
            channels = []
        return {
            "name": user.name,
            "email": user.email,
            "topics": topics,
            "keywords": pref.keywords if pref else "",
            "exclude_keywords": pref.exclude_keywords if pref else "",
            "push_channels": channels,
        }


def get_current_time(args: dict, ctx) -> dict:
    now = datetime.now()
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": f"星期{_WEEKDAYS[now.weekday()]}",
        "timezone": ctx.settings.app_timezone,
    }
