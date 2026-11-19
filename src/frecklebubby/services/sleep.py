"""Sleep prediction (deterministic, spec section 8) and total sleep recommendations."""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..db import utcnow
from ..models import Child, Entry, Timer
from .children import age_months, is_night

MARGIN = timedelta(minutes=15)


@lru_cache
def _table() -> dict:
    return json.loads((PACKAGE_DATA / "wake_windows.json").read_text())


def _matches(row: dict, months: float) -> bool:
    return row["min_months"] <= months and (row["max_months"] is None or months < row["max_months"])


def wake_range(months: float) -> tuple[int, int]:
    bands = _table()["wake_windows"]["bands"]
    row = next((b for b in bands if _matches(b, months)), bands[-1])
    return row["min_minutes"], row["max_minutes"]


def recommendations(months: float) -> list[dict]:
    """Recommended total sleep per 24 h for the age, one row per source (AASM 2016, NSF 2015)."""
    return [{k: r[k] for k in ("min_hours", "max_hours", "citation")}
            for r in _table()["total_sleep"] if _matches(r, months)]


def predict(s: Session, child: Child, tz, now: datetime | None = None, default: bool = False) -> dict | None:
    """Next sleep window. None while a sleep timer runs, or with no sleep in the last 24 h (unless default)."""
    now = now or utcnow()
    if s.scalar(select(Timer.id).where(Timer.child_id == child.id, Timer.type == "sleep")):
        return None
    lo, hi = wake_range(age_months(child, now))
    note = _table()["wake_windows"]["note"]
    sleeps = list(s.scalars(
        select(Entry).where(Entry.child_id == child.id, Entry.type == "sleep", Entry.ended_at.is_not(None),
                            Entry.started_at >= now - timedelta(days=8), Entry.ended_at <= now)
        .order_by(Entry.started_at)
    ))
    last = max(sleeps, key=lambda e: e.ended_at, default=None)
    if last is None or last.ended_at < now - timedelta(hours=24):
        if not default:
            return None
        ww = (lo + hi) // 2
        start = now + timedelta(minutes=ww) - MARGIN
        end = start + 2 * MARGIN
        return {"start": start, "end": end, "kind": "bedtime" if is_night(child, end.astimezone(tz)) else "nap",
                "basis": "age", "wake_window_minutes": ww, "samples": 0, "age_range_minutes": (lo, hi), "note": note}

    # Wake windows before each sleep, tagged with the nap number since the last night sleep.
    samples: list[tuple[int, float]] = []
    position = 0
    since = now - timedelta(days=7)
    prev = None
    for e in sleeps:
        night = is_night(child, e.started_at.astimezone(tz))
        if prev is not None and e.started_at >= since:
            gap = (e.started_at - prev[0].ended_at).total_seconds() / 60
            if gap > 0 and not (night and prev[1]):  # night to night is a night waking, not a wake window
                samples.append((position, gap))
        position = 0 if night else position + 1
        prev = (e, night)

    same = [g for p, g in samples if p == position]
    if len(same) >= 3:
        ww, basis, used = median(same), "personal", len(same)
    elif len(samples) >= 3:
        ww, basis, used = median(g for _, g in samples), "personal", len(samples)
    else:
        ww, basis, used = (lo + hi) / 2, "age", 0
    ww = round(min(max(ww, lo), hi))
    start = last.ended_at + timedelta(minutes=ww) - MARGIN
    end = start + 2 * MARGIN
    # A night waking (woke in the night, next window also in the night): the child sleeps again the same night.
    if is_night(child, last.ended_at.astimezone(tz), 0) and is_night(child, start.astimezone(tz), 0):
        return None
    kind = "bedtime" if is_night(child, end.astimezone(tz)) else "nap"
    return {"start": start, "end": end, "kind": kind, "basis": basis, "wake_window_minutes": ww,
            "samples": used, "age_range_minutes": (lo, hi), "note": note}
