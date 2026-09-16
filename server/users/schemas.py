"""用户模块请求模型（FR-U2 校验规则）。"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

TOPIC_OPTIONS = ["大模型", "AI 芯片", "自动驾驶", "AI 政策", "AI 应用"]

MAX_KEYWORDS = 20      # 逗号分隔后最多 20 个
MAX_KEYWORD_LEN = 30   # 单个关键词最长 30 字

_PUSH_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")   # HH:MM（00:00–23:59）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PUSH_CHANNELS = ("email", "wecom", "feishu", "dingtalk", "webhook", "serverchan", "pushplus")
WEBHOOK_CHANNELS = ("wecom", "feishu", "dingtalk", "webhook", "serverchan", "pushplus")


class ProfileIn(BaseModel):
    """PUT /api/profile 请求体。"""

    name: str = Field(min_length=1, max_length=100)
    email: str | None = None
    topics: list[str] = Field(default_factory=list)
    keywords: str = ""
    exclude_keywords: str = ""
    push_time: str = "08:00"
    push_channels: list[str] = Field(default_factory=list)   # 多选；空列表 = 仅网页查看
    channel_urls: dict[str, str] = Field(default_factory=dict)  # 渠道 -> 推送地址

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None  # 空字符串视为未填写
        if not _EMAIL_RE.match(value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("topics")
    @classmethod
    def _check_topics(cls, value: list[str]) -> list[str]:
        invalid = [t for t in value if t not in TOPIC_OPTIONS]
        if invalid:
            raise ValueError(f"不支持的话题 {invalid}；可选: {TOPIC_OPTIONS}")
        return value

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def _check_keywords(cls, value: str) -> str:
        parts = [p.strip() for p in re.split(r"[,，]", value or "") if p.strip()]
        if len(parts) > MAX_KEYWORDS:
            raise ValueError(f"关键词最多 {MAX_KEYWORDS} 个（当前 {len(parts)} 个）")
        too_long = [p for p in parts if len(p) > MAX_KEYWORD_LEN]
        if too_long:
            raise ValueError(f"单个关键词最长 {MAX_KEYWORD_LEN} 字: {too_long[:3]}")
        return value

    @field_validator("push_time")
    @classmethod
    def _check_push_time(cls, value: str) -> str:
        if not _PUSH_TIME_RE.match(value or ""):
            raise ValueError("push_time 必须为 HH:MM 格式（00:00–23:59）")
        return value

    @field_validator("push_channels")
    @classmethod
    def _check_channels(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("推送渠道不能重复")
        invalid = [c for c in value if c not in PUSH_CHANNELS]
        if invalid:
            raise ValueError(f"不支持的推送渠道 {invalid}；可选: {' / '.join(PUSH_CHANNELS)}")
        return value

    @field_validator("channel_urls")
    @classmethod
    def _check_channel_urls(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, url in (value or {}).items():
            url = (url or "").strip()
            if url and not url.startswith(("http://", "https://")):
                raise ValueError(f"渠道 {key} 的推送地址必须以 http:// 或 https:// 开头")
            cleaned[key] = url
        return cleaned
