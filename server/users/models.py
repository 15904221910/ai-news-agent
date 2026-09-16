"""用户与偏好 ORM 模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    preference: Mapped["Preference | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Preference(Base):
    __tablename__ = "preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    topics: Mapped[str] = mapped_column(Text, default="[]")          # JSON 数组字符串
    keywords: Mapped[str] = mapped_column(Text, default="")          # 逗号分隔
    exclude_keywords: Mapped[str] = mapped_column(Text, default="")
    push_time: Mapped[str] = mapped_column(String(5), default="08:00")   # HH:MM
    push_channels: Mapped[str] = mapped_column(Text, default="[]")   # JSON 数组：多选推送渠道（空=仅网页查看）
    channel_urls: Mapped[str] = mapped_column(Text, default="{}")    # JSON 对象：渠道 -> 推送地址
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    user: Mapped[User] = relationship(back_populates="preference")
