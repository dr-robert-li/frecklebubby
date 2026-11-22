"""Entries: validation, create, list, update, delete."""

from datetime import datetime, timedelta
from typing import Any, get_args

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Child, Entry
from ..plugins import registry
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
    registry.emit("entry_saved", entry=entry)
    return entry


def get_entry(s: Session, ctx: Ctx, entry_id: int) -> Entry:
    entry = s.scalar(
        select(Entry).join(Child).where(Entry.id == entry_id, Child.family_id == ctx.fam.id)
    )
    if entry is None:
        raise NotFound("Entry not found.")
    return entry


def _num(key: str):
    return func.json_extract(Entry.data, f"$.{key}")


# The logged amount of an entry, by name. The list can be in the order of one of these.
MEASURES = {
    "duration": lambda: func.coalesce(
        (func.julianday(Entry.ended_at) - func.julianday(Entry.started_at)) * 86400,
        _num("left_seconds") + _num("right_seconds"), _num("left_seconds"), _num("right_seconds")),
    "volume": lambda: func.coalesce(_num("amount_ml"), _num("total_ml"), _num("left_ml") + _num("right_ml"),
                                    _num("left_ml"), _num("right_ml")),
    "weight": lambda: _num("weight_kg"),
    "height": lambda: _num("height_cm"),
    "head": lambda: _num("head_cm"),
    "temperature": lambda: _num("celsius"),
}


def list_entries(s: Session, ctx: Ctx, child_id: int, type_: str | list[str] | None = None,
                 start: datetime | None = None, end: datetime | None = None, limit: int | None = 50,
                 before: datetime | None = None, newest_first: bool = True, sort: str = "time",
                 offset: int = 0) -> list[Entry]:
    """Entries that start in [start, end) and before `before` (page cursor). `sort` is "time" or a name in MEASURES;
    with a measure, entries that do not have it are left out, and `newest_first` means largest first.
    `limit` None gives all entries (for the export)."""
    child = get_child(s, ctx, child_id)
    q = select(Entry).where(Entry.child_id == child.id)
    if type_ is not None:
        q = q.where(Entry.type.in_([type_] if isinstance(type_, str) else type_))
    if start:
        q = q.where(Entry.started_at >= to_utc(start, ctx.tz))
    if end:
        q = q.where(Entry.started_at < to_utc(end, ctx.tz))
    if before:
        q = q.where(Entry.started_at < to_utc(before, ctx.tz))
    order = (Entry.started_at.desc(), Entry.id.desc()) if newest_first else (Entry.started_at, Entry.id)
    if sort != "time":
        m = MEASURES[sort]()
        q = q.where(m.is_not(None))
        order = (m.desc() if newest_first else m.asc(), Entry.started_at.desc(), Entry.id.desc())
    return list(s.scalars(q.order_by(*order).offset(offset).limit(limit and max(1, min(limit, 1000)))))


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
    registry.emit("entry_saved", entry=entry)
    return entry


def delete_entry(s: Session, ctx: Ctx, entry_id: int) -> None:
    entry = get_entry(s, ctx, entry_id)
    s.delete(entry)
    s.commit()
    registry.emit("entry_deleted", entry=entry)


def last_entries(s: Session, child_id: int) -> dict[str, Entry]:
    """Latest entry of each type. Caller has checked the child belongs to the family."""
    out = {}
    for t in get_args(EntryType):
        e = s.scalar(select(Entry).where(Entry.child_id == child_id, Entry.type == t)
                     .order_by(Entry.started_at.desc(), Entry.id.desc()).limit(1))
        if e:
            out[t] = e
    return out
