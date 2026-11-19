"""Live timers for sleep, nursing, pump and activity. complete() turns a timer into an entry."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Entry, Timer
from ..schemas import TimerBody
from . import Conflict, Ctx, Invalid, NotFound, to_utc
from .children import get_child
from .entries import FUTURE_LIMIT, validate

TIMER_TYPES = ("sleep", "nursing", "pump", "activity")


def elapsed(t: Timer, now: datetime) -> int:
    return max(0, int(((t.paused_at or now) - t.started_at).total_seconds()) - t.paused_seconds)


def timer_out(t: Timer, now: datetime) -> dict:
    return {"type": t.type, "started_at": t.started_at, "paused_at": t.paused_at,
            "paused_seconds": t.paused_seconds, "data": t.data, "elapsed_seconds": elapsed(t, now)}


def list_timers(s: Session, child_id: int) -> list[Timer]:
    """Caller has checked the child belongs to the family."""
    return list(s.scalars(select(Timer).where(Timer.child_id == child_id).order_by(Timer.id)))


def _close_side(data: dict, until: datetime) -> dict:
    """Nursing: add the time on the current side since side_since to that side's total."""
    data = dict(data)
    if data.get("side_since"):
        since = datetime.fromisoformat(data["side_since"])
        key = f"{data['side']}_seconds"
        data[key] = data.get(key, 0) + max(0, int((until - since).total_seconds()))
    data["side_since"] = None
    return data


def act(s: Session, ctx: Ctx, child_id: int, type_: str, action: str, body: TimerBody,
        now: datetime | None = None) -> tuple[Timer | None, Entry | None]:
    if type_ not in TIMER_TYPES:
        raise NotFound(f"No timer type {type_!r}. Use sleep, nursing, pump or activity.")
    now = now or utcnow()
    child = get_child(s, ctx, child_id)
    at = to_utc(body.at, ctx.tz) if body.at else None
    if at and action not in ("start", "complete"):
        raise Invalid("at: use it only with start or complete")
    if body.side and not (type_ == "nursing" and action in ("start", "resume", "switch")):
        raise Invalid("side: use it only with a nursing timer")
    if body.kind and not (type_ == "activity" and action in ("start", "switch")):
        raise Invalid("kind: use it only with an activity timer")
    if (body.data is not None or body.notes is not None) and action != "complete":
        raise Invalid("data and notes: use them only with complete")

    t = s.scalar(select(Timer).where(Timer.child_id == child.id, Timer.type == type_))
    if t is None and action != "start":
        raise NotFound(f"No {type_} timer is running.")

    if action == "start":
        start = at or now
        if start > now + FUTURE_LIMIT:
            raise Invalid("at: must not be more than 5 minutes in the future")
        if t is None:
            data: dict = {}
            if type_ == "nursing":
                data = {"side": body.side or "left", "left_seconds": 0, "right_seconds": 0,
                        "side_since": start.isoformat()}
            elif type_ == "activity":
                if not body.kind:
                    raise Invalid("kind: required to start an activity timer")
                data = {"kind": body.kind}
            t = Timer(child_id=child.id, type=type_, started_at=start, paused_seconds=0, data=data,
                      started_by=ctx.user.id)
            s.add(t)
        else:
            # Starting a running timer moves its start time.
            if t.paused_at and start > t.paused_at:
                raise Invalid("at: must be before the time the timer was paused")
            data = dict(t.data)
            if type_ == "nursing" and data.get("side_since"):
                # The moved time belongs to the side that runs now.
                since = datetime.fromisoformat(data["side_since"]) + (start - t.started_at)
                data["side_since"] = min(max(since, start), now).isoformat()
            if type_ == "nursing" and body.side and body.side != data["side"]:
                data = _close_side(data, now) | {"side": body.side, "side_since": None if t.paused_at else now.isoformat()}
            if type_ == "activity" and body.kind:
                data["kind"] = body.kind
            t.started_at, t.data = start, data
    elif action == "pause":
        if t.paused_at:
            raise Conflict("The timer is already paused.")
        if type_ == "nursing":
            t.data = _close_side(t.data, now)
        t.paused_at = now
    elif action == "resume":
        if not t.paused_at:
            raise Conflict("The timer is not paused.")
        t.paused_seconds += int((now - t.paused_at).total_seconds())
        t.paused_at = None
        if type_ == "nursing":
            t.data = {**t.data, "side": body.side or t.data["side"], "side_since": now.isoformat()}
    elif action == "switch":
        if type_ == "nursing":
            data = _close_side(t.data, now) if not t.paused_at else dict(t.data)
            data["side"] = body.side or ("right" if data["side"] == "left" else "left")
            data["side_since"] = None if t.paused_at else now.isoformat()
            t.data = data
        elif type_ == "activity":
            if not body.kind:
                raise Invalid("kind: required to switch an activity timer")
            t.data = {**t.data, "kind": body.kind}
        else:
            raise Invalid("switch: use it only with a nursing or activity timer")
    elif action == "cancel":
        s.delete(t)
        s.commit()
        return None, None
    elif action == "complete":
        end = at or t.paused_at or now
        if end < t.started_at:
            raise Invalid("at: the end must be after the start")
        data = dict(body.data or {})
        if type_ == "nursing":
            nd = _close_side(t.data, min(end, now)) if not t.paused_at else t.data
            data = {"left_seconds": nd.get("left_seconds", 0), "right_seconds": nd.get("right_seconds", 0),
                    "last_side": nd["side"]} | data
        elif type_ == "activity":
            data = {"kind": t.data["kind"]} | data
        # shortcut: the entry spans start to end and paused time is not removed (except nursing side seconds);
        # store paused_seconds in the entry if users need net durations.
        data = validate(type_, t.started_at, end, data, body.notes, now)
        entry = Entry(child_id=child.id, type=type_, started_at=t.started_at, ended_at=end, data=data,
                      notes=body.notes or None, source=ctx.source, created_by=ctx.user.id)
        s.add(entry)
        s.delete(t)
        s.commit()
        return None, entry
    else:
        raise NotFound(f"No timer action {action!r}.")
    s.commit()
    return t, None
