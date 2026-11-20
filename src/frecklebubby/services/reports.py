"""Daily report and status. A day is a day in the family time zone."""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Entry, Notification
from ..schemas import ActivityDay, DayReport
from . import Ctx, Invalid, day_bounds
from .children import age_months, get_child, is_night
from .confined import merge, now_info, under
from .entries import last_entries
from .library import source
from .sleep import predict, recommendations
from .timers import list_timers, timer_out

PLAY_KINDS = ("tummyTime", "indoorPlay", "outdoorPlay")  # activity kinds that count as play
# WHO 2019 (who-under-5-activity-sleep.md): "For infants not yet mobile, this includes at least 30 minutes in prone
# position (tummy time)"; checked in tests/test_m9.py.
TUMMY = {"minutes": 30, "under_months": 12, "source": "who-under-5-activity-sleep",
         "text": "WHO: at least 30 minutes of tummy time a day, spread through the day, for babies under 1 year "
                 "who are not yet mobile."}


def _seconds(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds()))


def tummy_recommendation(child, day: date) -> dict | None:
    if not under(child, day, TUMMY["under_months"]):
        return None
    return {"minutes": TUMMY["minutes"], "text": TUMMY["text"], "citation": source(TUMMY["source"])}


def daily(s: Session, ctx: Ctx, child_id: int, start: date | None = None, end: date | None = None,
          now: datetime | None = None) -> dict:
    child = get_child(s, ctx, child_id)
    tz, now = ctx.tz, now or utcnow()
    end = end or now.astimezone(tz).date()
    start = start or end - timedelta(days=6)
    if end < start:
        raise Invalid("to: must not be before from")
    if (end - start).days > 366:
        raise Invalid("from, to: the range must be one year or less")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    bounds = [day_bounds(d, tz) for d in days]
    reports = [DayReport(date=d) for d in days]
    lo, hi = bounds[0][0], bounds[-1][1]
    confined_spans: dict[date, list] = {}
    play_spans: dict[date, list] = {}
    tummy_spans: dict[date, list] = {}

    # Sleeps that start up to 2 days earlier can reach into the range.
    entries = s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.started_at >= lo - timedelta(days=2),
                                            Entry.started_at < hi))
    for e in entries:
        if e.type == "sleep" and e.ended_at:
            nap = not is_night(child, e.started_at.astimezone(tz))
            for (ds, de), r in zip(bounds, reports, strict=True):
                part = _seconds(max(e.started_at, ds), min(e.ended_at, de))
                starts_here = ds <= e.started_at < de
                if not part and not starts_here:
                    continue
                r.sleep.total_seconds += part
                if nap:
                    r.sleep.nap_seconds += part
                else:
                    r.sleep.night_seconds += part
                if starts_here:
                    r.sleep.count += 1
                    r.sleep.nap_count += nap
            continue
        r = next((r for (ds, de), r in zip(bounds, reports, strict=True) if ds <= e.started_at < de), None)
        if r is None:
            continue
        d = e.data
        duration = _seconds(e.started_at, e.ended_at) if e.ended_at else 0
        if e.type == "nursing":
            r.feeds.count += 1
            r.feeds.nursing_seconds += int(d.get("left_seconds", 0) + d.get("right_seconds", 0)) or duration
        elif e.type == "bottle":
            r.feeds.count += 1
            r.feeds.bottle_ml += d.get("amount_ml", 0)
        elif e.type == "solids":
            r.feeds.solids_count += 1
        elif e.type == "nappy":
            r.nappies.wet += d["mode"] in ("pee", "both")
            r.nappies.dirty += d["mode"] in ("poo", "both")
            r.nappies.air_minutes += int(d.get("air_minutes", 0))
            r.nappies.rash += bool(d.get("rash"))
        elif e.type == "pump":
            r.pump_ml += d.get("total_ml", 0)
        elif e.type == "medicine":
            r.medicine_count += 1
        elif e.type == "activity":
            a = r.activities.setdefault(d["kind"], ActivityDay())
            a.count += 1
            a.seconds += duration
            r.bath_count += d["kind"] == "bath"
            span = (e.started_at, e.ended_at or e.started_at)
            if d["kind"] in PLAY_KINDS:
                play_spans.setdefault(r.date, []).append(span)
            if d["kind"] == "tummyTime":
                tummy_spans.setdefault(r.date, []).append(span)
        elif e.type == "cry":
            r.crying.count += 1
            r.crying.seconds += duration
        elif e.type == "confined":
            r.confined.count += 1
            r.confined.seconds += duration
            if e.ended_at:
                confined_spans.setdefault(r.date, []).append((e.started_at, e.ended_at))
    for r in reports:
        # Longest continuous period of the entries that start on this day.
        r.confined.longest_seconds = max((_seconds(a, b) for a, b in merge(confined_spans.get(r.date, []))), default=0)
        # Play timers can run in parallel (indoor play and tummy time): overlapping time counts once.
        play = merge(play_spans.get(r.date, []), timedelta(0))
        r.play.count, r.play.seconds = len(play), sum(_seconds(a, b) for a, b in play)
        r.play.tummy_seconds = sum(_seconds(a, b) for a, b in merge(tummy_spans.get(r.date, []), timedelta(0)))
    return {"timezone": ctx.fam.timezone, "sleep_recommendations": recommendations(age_months(child, now)),
            "tummy_recommendation": tummy_recommendation(child, now.astimezone(tz).date()), "days": reports}


def status(s: Session, ctx: Ctx, child_id: int, now: datetime | None = None) -> dict:
    child = get_child(s, ctx, child_id)
    now = now or utcnow()
    today = now.astimezone(ctx.tz).date()
    unread = s.scalar(select(func.count()).select_from(Notification)
                      .where(Notification.family_id == ctx.fam.id, Notification.read_at.is_(None)))
    return {
        "now": now,
        "timers": [timer_out(t, now) for t in list_timers(s, child.id)],
        "last": last_entries(s, child.id),
        "today": daily(s, ctx, child.id, today, today, now)["days"][0],
        "prediction": predict(s, child, ctx.tz, now),
        "unread_notifications": unread,
        "confined": now_info(s, child, ctx.tz, now),
    }
