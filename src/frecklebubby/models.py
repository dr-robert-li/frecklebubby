"""SQLAlchemy tables (spec section 4). kb_chunk is an FTS5 table made in db.init_db."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow


def _id() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True)


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = _id()
    clerk_sub: Mapped[str | None] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = _created()


class Family(Base):
    __tablename__ = "family"
    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "membership"
    # One family per user in v0.1, so user_id is the key.
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)  # owner | carer


class Invite(Base):
    __tablename__ = "invite"
    id: Mapped[int] = _id()
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class Child(Base):
    __tablename__ = "child"
    id: Mapped[int] = _id()
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    birthdate: Mapped[date] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(1))
    color: Mapped[str] = mapped_column(String, default="#B9A8E8")
    night_start: Mapped[str] = mapped_column(String(5), default="19:00")
    morning_cutoff: Mapped[str] = mapped_column(String(5), default="07:00")
    external_id: Mapped[str | None] = mapped_column(String, unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class Entry(Base):
    __tablename__ = "entry"
    __table_args__ = (Index("ix_entry_child_started", "child_id", "started_at"),)
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, default="app")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Timer(Base):
    __tablename__ = "timer"
    __table_args__ = (UniqueConstraint("child_id", "type"),)
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))


class Reminder(Base):
    __tablename__ = "reminder"
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)  # in | at
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    times: Mapped[list[str]] = mapped_column(JSON, default=list)
    days: Mapped[list[int]] = mapped_column(JSON, default=list)
    daytime_only: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = _id()
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    child_id: Mapped[int | None] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PushSubscription(Base):
    __tablename__ = "push_subscription"
    id: Mapped[int] = _id()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)


class ApiToken(Base):
    __tablename__ = "api_token"
    id: Mapped[int] = _id()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()


class KbSource(Base):
    __tablename__ = "kb_source"
    id: Mapped[int] = _id()
    family_id: Mapped[int | None] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String)  # bundled | link | upload | web
    title: Mapped[str] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String)
    publisher: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _created()


class SleepPlan(Base):
    __tablename__ = "sleep_plan"
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    citations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _created()


class SupportReport(Base):
    """The last support report of a child (M11). A new report replaces the old one."""

    __tablename__ = "support_report"
    id: Mapped[int] = _id()
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = _created()
    days: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ImportJob(Base):
    __tablename__ = "import_job"
    id: Mapped[int] = _id()
    family_id: Mapped[int] = mapped_column(ForeignKey("family.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
