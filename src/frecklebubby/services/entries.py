"""Entries: validation, create, list, update, delete."""

from datetime import datetime, timedelta
from typing import Any, get_args

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Child, Entry
from ..schemas import DATA_MODELS, END_OPTIONAL, END_REQUIRED, EntryIn, EntryPatch, EntryType
from . import Ctx, Invalid, NotFound, plain_errors, to_utc
from .children import get_child

FUTURE_LIMIT = timedelta(minutes=5)


def validate(type_: str, started_at: datetime, ended_at: datetime | None, data: dict[str, Any],
             notes: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Check times and data for one entry. Returns the clean data. Used by REST, MCP, timers and NL logging."""
    if type_ not in DATA_MODELS:
        raise Invalid(f"type: unknown entry type {type_!r}")
    limit = (now or utcnow()) + FUTURE_LIMIT
    if started_at > limit:
        raise Invalid("started_at: must not be more than 5 minutes in the future")
    if ended_at is not None:
        if type_ not in END_REQUIRED | END_OPTIONAL:
            raise Invalid(f"ended_at: a {type_} entry has no end time")
        if ended_at < started_at:
            raise Invalid("ended_at: must be after started_at")
        if ended_at > limit:
            raise Invalid("ended_at: must not be more than 5 minutes in the future")
    elif type_ in END_REQUIRED:
        raise Invalid(f"ended_at: required for {type_}")
    if type_ == "note" and not (notes or "").strip():
        raise Invalid("notes: required for a note")
    try:
        return DATA_MODELS[type_].model_validate(data).model_dump(exclude_none=True)
    except ValidationError as err:
        raise Invalid(plain_errors(err, "data")) from err


def create_entry(s: Session, ctx: Ctx, child_id: int, body: EntryIn, external_id: str | None = None) -> Entry:
    child = get_child(s, ctx, child_id)
    started = to_utc(body.started_at, ctx.tz)
    ended = to_utc(body.ended_at, ctx.tz) if body.ended_at else None
    data = validate(body.type, started, ended, body.data, body.notes)
    entry = Entry(child_id=child.id, type=body.type, started_at=started, ended_at=ended, data=data,
                  notes=body.notes or None, source=ctx.source, created_by=ctx.user.id, external_id=external_id)
    s.add(entry)
    s.commit()
    return entry


def get_entry(s: Session, ctx: Ctx, entry_id: int) -> Entry:
    entry = s.scalar(
        select(Entry).join(Child).where(Entry.id == entry_id, Child.family_id == ctx.fam.id)
    )
    if entry is None:
        raise NotFound("Entry not found.")
    return entry


def list_entries(s: Session, ctx: Ctx, child_id: int, type_: str | None = None, start: datetime | None = None,
                 end: datetime | None = None, limit: int = 50, before: datetime | None = None,
                 newest_first: bool = True) -> list[Entry]:
    """Entries that start in [start, end) and before `before` (page cursor)."""
    child = get_child(s, ctx, child_id)
    q = select(Entry).where(Entry.child_id == child.id)
    if type_:
        q = q.where(Entry.type == type_)
    if start:
        q = q.where(Entry.started_at >= to_utc(start, ctx.tz))
    if end:
        q = q.where(Entry.started_at < to_utc(end, ctx.tz))
    if before:
        q = q.where(Entry.started_at < to_utc(before, ctx.tz))
    order = (Entry.started_at.desc(), Entry.id.desc()) if newest_first else (Entry.started_at, Entry.id)
    return list(s.scalars(q.order_by(*order).limit(max(1, min(limit, 1000)))))


def update_entry(s: Session, ctx: Ctx, entry_id: int, body: EntryPatch) -> Entry:
    entry = get_entry(s, ctx, entry_id)
    changes = body.model_dump(exclude_unset=True)
    if "started_at" in changes and changes["started_at"] is None:
        raise Invalid("started_at: must not be null")
    started = to_utc(body.started_at, ctx.tz) if body.started_at else entry.started_at
    ended = entry.ended_at
    if "ended_at" in changes:
        ended = to_utc(body.ended_at, ctx.tz) if body.ended_at else None
    notes = changes.get("notes", entry.notes)
    data = validate(entry.type, started, ended, body.data if body.data is not None else entry.data, notes)
    entry.started_at, entry.ended_at, entry.data, entry.notes = started, ended, data, notes or None
    s.commit()
    return entry


def delete_entry(s: Session, ctx: Ctx, entry_id: int) -> None:
    s.delete(get_entry(s, ctx, entry_id))
    s.commit()


def last_entries(s: Session, child_id: int) -> dict[str, Entry]:
    """Latest entry of each type. Caller has checked the child belongs to the family."""
    out = {}
    for t in get_args(EntryType):
        e = s.scalar(select(Entry).where(Entry.child_id == child_id, Entry.type == t)
                     .order_by(Entry.started_at.desc(), Entry.id.desc()).limit(1))
        if e:
            out[t] = e
    return out
