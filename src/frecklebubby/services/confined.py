"""Confined time (car seat, pram, bouncer and so on): continuous periods, the 1-hour note and the 2-hour warning.

Continuous time = the running confined timer plus finished confined entries that touch it with a gap of GAP or less
(a short stop does not reset the clock). Deterministic, no model. The thresholds and their sources are here, beside
the rule. Each fact in the text has a SUPPORT phrase; tests/test_m9.py checks that the phrase is in the cited file.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Entry, Family, Timer
from . import zone
from .library import cite
from .notifications import notify

log = logging.getLogger(__name__)

GAP = timedelta(minutes=10)
# WHO 2019: children under 5 should not be restrained for more than 1 hour at a time.
NOTE = {"seconds": 3600, "under_months": 60}
# 2 hours under 12 months is the user's decision (DEVIATIONS.md M9): AAP says to take a break every 2 to 3 hours on a
# day trip (car-seat-time.md). No source gives the age; the text says only what the sources say.
WARNING = {"seconds": 7200, "under_months": 12}

WHO, NHS_ACTIVE, CAR = "who-under-5-activity-sleep", "nhs-keep-baby-active", "car-seat-time"
SUPPORT = {
    "who_1h": (WHO, "should not be restrained for more than 1 hour at a time"),
    "who_devices": (WHO, "WHO counts time restrained in car seats, high chairs, strollers"),
    "break": (NHS_ACTIVE, "consider taking a break and getting your child out of their seat for a bit"),
    "seats_20min": (NHS_ACTIVE, "it's best to use them for no more than 20 minutes at a time"),
    "aap": (CAR, "take a break every 2 to 3 hours on a day trip"),
    "aap_night": (CAR, "On a night trip it says every 4 to 6 hours."),
}

PLACES = {"car_seat": "in the car seat", "bouncer": "in the bouncer", "swing": "in the swing", "pram": "in the pram",
          "carrier": "in the carrier", "high_chair": "in the high chair", "other": "strapped in"}


def under(child: Child, day: date, months: int) -> bool:
    """True if the child is younger than `months` calendar months on this day."""
    b = child.birthdate
    y, m = divmod(b.month - 1 + months, 12)
    return (day.year, day.month, day.day) < (b.year + y, m + 1, b.day)


def merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Join spans that overlap or have a gap of GAP or less."""
    out: list[tuple[datetime, datetime]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] <= GAP:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def current(s: Session, child: Child, now: datetime) -> dict | None:
    """The continuous period of the running confined timer, or None."""
    t = s.scalar(select(Timer).where(Timer.child_id == child.id, Timer.type == "confined"))
    if t is None:
        return None
    end = t.paused_at or now
    rows = s.execute(select(Entry.started_at, Entry.ended_at).where(
        Entry.child_id == child.id, Entry.type == "confined", Entry.ended_at.is_not(None),
        Entry.started_at >= t.started_at - timedelta(days=1), Entry.started_at <= end)).all()
    periods = merge([(a, b) for a, b in rows] + [(t.started_at, end)])
    since = next(a for a, b in periods if a <= t.started_at <= b)
    return {"since": since, "device": t.data.get("device", "other"), "seconds": int((end - since).total_seconds())}


def levels(child: Child, device: str, day: date) -> dict:
    """Note and warning texts for this child and device; None where the age rule does not apply."""
    name, place = child.name, PLACES.get(device, PLACES["other"])
    note = warning = None
    if under(child, day, NOTE["under_months"]):
        note = {"after_seconds": NOTE["seconds"], "title": f"{name}: {place} for 1 hour",
                "text": f"{name} has been {place} for 1 hour. WHO advises that children under 5 are not restrained "
                        "for more than 1 hour at a time, for example in a car seat, pram or high chair. When it is "
                        f"safe, take a break and get {name} out of the seat to move.",
                "citations": cite(WHO, NHS_ACTIVE)}
    if under(child, day, WARNING["under_months"]):
        if device == "car_seat":
            text = ("HealthyChildren.org (AAP) says to take a break every 2 to 3 hours on a day trip, and every 4 to "
                    "6 hours on a night trip.")
            sources = (CAR,)
        else:
            text = ("WHO advises that children under 5 are not restrained for more than 1 hour at a time. The NHS "
                    "says to use a bouncer or seat for no more than 20 minutes at a time.")
            sources = (WHO, NHS_ACTIVE)
        warning = {"after_seconds": WARNING["seconds"], "title": f"{name}: time for a break",
                   "text": f"{name} has been {place} for 2 hours. It is time for a break. {text} When it is safe, "
                           f"take {name} out of the seat.",
                   "citations": cite(*sources)}
    return {"note": note, "warning": warning}


def now_info(s: Session, child: Child, tz, now: datetime) -> dict | None:
    """Status block while a confined timer runs."""
    cur = current(s, child, now)
    return None if cur is None else cur | levels(child, cur["device"], now.astimezone(tz).date())


def tick(s: Session, now: datetime) -> int:
    """Send the note and the warning once per continuous period. Called by the reminder tick."""
    fired = 0
    rows = s.execute(select(Timer, Child, Family).join(Child, Timer.child_id == Child.id)
                     .join(Family, Child.family_id == Family.id)
                     .where(Timer.type == "confined", Child.archived.is_(False))).all()
    for _, child, family in rows:
        try:
            info = now_info(s, child, zone(family.timezone), now)
            for level in ("note", "warning"):
                lv = info and info[level]
                if lv and info["seconds"] >= lv["after_seconds"] and notify(
                        s, family.id, child.id, f"confined:{level}", lv["title"], lv["text"],
                        f"confined:{child.id}:{level}:{info['since'].isoformat()}"):
                    fired += 1
        except Exception:
            s.rollback()
            log.exception("Confined check for child %s failed", child.id)
    return fired

