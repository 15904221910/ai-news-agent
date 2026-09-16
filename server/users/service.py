"""用户与偏好服务：种子数据（幂等）/ 读取 / 保存。"""
from __future__ import annotations

import json
import logging

from server.config import get_settings
from server.database import session_scope
from server.errors import NotFoundAppError, ValidationAppError
from server.users.models import Preference, User
from server.users.schemas import ProfileIn, WEBHOOK_CHANNELS

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = 1  # 单用户系统：出厂种子用户（§1.3）

SEED_USER = {"name": "Demo User", "email": None}
SEED_PREFERENCE = {
    "topics": ["大模型", "AI 芯片"],
    "keywords": "GPT, 多模态",
    "exclude_keywords": "融资, 股价",
    "push_time": "08:00",
    "push_channels": [],
    "channel_urls": {},
}


def ensure_seed_data() -> None:
    """幂等种子数据：user_id=1 + 默认偏好（main 启动与 scripts/seed.py 共用）。"""
    with session_scope() as session:
        if session.get(User, DEFAULT_USER_ID) is None:
            session.add(User(id=DEFAULT_USER_ID, name=SEED_USER["name"], email=SEED_USER["email"]))
            logger.info("已创建种子用户", extra={"user_id": DEFAULT_USER_ID})
        if session.get(Preference, DEFAULT_USER_ID) is None:
            session.add(
                Preference(
                    user_id=DEFAULT_USER_ID,
                    topics=json.dumps(SEED_PREFERENCE["topics"], ensure_ascii=False),
                    keywords=SEED_PREFERENCE["keywords"],
                    exclude_keywords=SEED_PREFERENCE["exclude_keywords"],
                    push_time=SEED_PREFERENCE["push_time"],
                    push_channels=json.dumps(SEED_PREFERENCE["push_channels"]),
                    channel_urls=json.dumps(SEED_PREFERENCE["channel_urls"]),
                )
            )
            logger.info("已创建种子偏好", extra={"user_id": DEFAULT_USER_ID})


def get_profile(user_id: int = DEFAULT_USER_ID) -> dict:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundAppError(f"用户不存在: {user_id}", code="USER_NOT_FOUND")
        pref = session.get(Preference, user_id)
        if pref is None:  # 自愈：偏好缺失时补默认值，保证前端表单可直接编辑
            pref = _default_preference(user_id)
            session.add(pref)
            session.flush()
        return _profile_dict(user, pref)


def upsert_profile(user_id: int, payload: ProfileIn) -> dict:
    _validate_push_channels(payload)
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundAppError(f"用户不存在: {user_id}", code="USER_NOT_FOUND")
        user.name = payload.name
        user.email = payload.email

        pref = session.get(Preference, user_id)
        if pref is None:
            pref = _default_preference(user_id)
            session.add(pref)
        pref.topics = json.dumps(payload.topics, ensure_ascii=False)
        pref.keywords = payload.keywords
        pref.exclude_keywords = payload.exclude_keywords
        pref.push_time = payload.push_time
        pref.push_channels = json.dumps(payload.push_channels, ensure_ascii=False)
        pref.channel_urls = json.dumps(payload.channel_urls, ensure_ascii=False)
        session.flush()
        return _profile_dict(user, pref)



def _validate_push_channels(payload: ProfileIn) -> None:
    """FR-U2：选中的 webhook 类渠道必须有地址；email 渠道需邮箱 + SMTP 配置。"""
    missing_urls = [
        ch for ch in payload.push_channels
        if ch in WEBHOOK_CHANNELS and not payload.channel_urls.get(ch)
    ]
    if missing_urls:
        raise ValidationAppError(
            f"渠道 {'、'.join(missing_urls)} 需要填写推送地址（Webhook URL）"
        )
    if "email" not in payload.push_channels:
        return
    if not payload.email:
        raise ValidationAppError("推送渠道包含 email 时必须填写邮箱")
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USER", settings.smtp_user),
            ("SMTP_PASS", settings.smtp_pass),
            ("SMTP_FROM", settings.smtp_from),
        )
        if not value
    ]
    if missing:
        raise ValidationAppError(f"邮件渠道需要配置 {'、'.join(missing)}（参考 .env.example）")


def _default_preference(user_id: int) -> Preference:
    return Preference(
        user_id=user_id,
        topics=json.dumps(SEED_PREFERENCE["topics"], ensure_ascii=False),
        keywords=SEED_PREFERENCE["keywords"],
        exclude_keywords=SEED_PREFERENCE["exclude_keywords"],
        push_time=SEED_PREFERENCE["push_time"],
        push_channels=json.dumps(SEED_PREFERENCE["push_channels"]),
        channel_urls=json.dumps(SEED_PREFERENCE["channel_urls"]),
    )


def _load_json(raw: str | None, fallback):  # noqa: ANN001
    """容错解析 JSON 列：类型不匹配或损坏时回退默认值。"""
    try:
        value = json.loads(raw) if raw else fallback
    except json.JSONDecodeError:
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _profile_dict(user: User, pref: Preference) -> dict:
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email},
        "preferences": {
            "topics": _load_json(pref.topics, []),
            "keywords": pref.keywords or "",
            "exclude_keywords": pref.exclude_keywords or "",
            "push_time": pref.push_time or "08:00",
            "push_channels": _load_json(pref.push_channels, []),
            "channel_urls": _load_json(pref.channel_urls, {}),
        },
    }
