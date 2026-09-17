# -*- coding: utf-8 -*-
"""元工具回归测试：get_user_profile 与 Preference 模型字段保持一致。

背景：多选渠道重构后（push_channel → push_channels/channel_urls），
工具层曾残留旧的 pref.push_channel 引用导致 AttributeError（Agent 每步重试）。
"""
from __future__ import annotations

import json

from server.agent.tools.meta_tools import get_current_time, get_user_profile
from server.database import session_scope
from server.users.models import Preference


def test_get_user_profile_reads_multi_channel_fields(run_ctx):
    """返回勾选渠道列表；推送地址（含密钥）绝不进入工具结果。"""
    with session_scope() as session:
        pref = session.get(Preference, run_ctx.user_id)
        pref.push_channels = json.dumps(["serverchan", "pushplus"])
        pref.channel_urls = json.dumps({"serverchan": "https://sctapi.ftqq.com/SECRET_KEY.send"})

    result = get_user_profile({}, run_ctx)

    assert result["name"]
    assert result["push_channels"] == ["serverchan", "pushplus"]
    assert "SECRET_KEY" not in json.dumps(result, ensure_ascii=False)


def test_get_user_profile_tolerates_missing_preference(run_ctx):
    """偏好行缺失时返回空值而不是抛异常。"""
    with session_scope() as session:
        session.delete(session.get(Preference, run_ctx.user_id))

    result = get_user_profile({}, run_ctx)

    assert result["topics"] == []
    assert result["push_channels"] == []
    assert result["keywords"] == ""


def test_get_current_time_shape(run_ctx):
    result = get_current_time({}, run_ctx)
    assert set(result) == {"datetime", "date", "weekday", "timezone"}
    assert result["date"] in result["datetime"]
