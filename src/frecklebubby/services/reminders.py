"""Reminders and the reminder engine. tick(now) runs each 60 s in the app process."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Entry, Family, Reminder
from ..schemas import ReminderIn, ReminderPatch
from . import Ctx, Invalid, NotFound, hm, zone
from .children import get_child, is_night
from .families import wording
from .notifications import notify
from .sleep import predict

log = logging.getLogger(__name__)

AT_GRACE = timedelta(minutes=15)  # an "at" reminder still fires this long after its time (restart, slow tick)
LABELS = {"nursing": "breastfeed", "growth": "growth check", "temperature": "temperature check"}


def _check(type_: str, mode: str, interval: int | None, times: list[str]) -> None:
    if type_ == "sleep_alert" and mode != "in":
        raise Invalid("mode: a sleep_alert uses mode 'in' with interval_minutes = minutes before the sleep window")
    if mode == "in" and not interval:
        raise Invalid("interval_minutes: required for mode 'in'")
    if mode == "at" and not times:
        raise Invalid("times: give one or more times (HH:MM) for mode 'at'")


def get_reminder(s: Session, ctx: Ctx, reminder_id: int) -> Reminder:
    r = s.scalar(select(Reminder).join(Child).where(Reminder.id == reminder_id, Child.family_id == ctx.fam.id))
    if r is None:
        raise NotFound("Reminder not found.")
    return r


def list_reminders(s: Session, ctx: Ctx, child_id: int) -> list[Reminder]:
    child = get_child(s, ctx, child_id)
    return list(s.scalars(select(Reminder).where(Reminder.child_id == child.id).order_by(Reminder.id)))


def create_reminder(s: Session, ctx: Ctx, child_id: int, body: ReminderIn) -> Reminder:
    child = get_child(s, ctx, child_id)
    _check(body.type, body.mode, body.interval_minutes, body.times)
    r = Reminder(child_id=child.id, **body.model_dump())
    s.add(r)
    s.commit()
    return r


def update_reminder(s: Session, ctx: Ctx, reminder_id: int, body: ReminderPatch) -> Reminder:
    r = get_reminder(s, ctx, reminder_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("times", "days", "daytime_only", "enabled"):
        if key in changes and changes[key] is None:
            raise Invalid(f"{key}: must not be null")
    _check(r.type, r.mode, changes.get("interval_minutes", r.interval_minutes), changes.get("times", r.times))
    for key, value in changes.items():
        setattr(r, key, value)
    s.commit()
    return r


def delete_reminder(s: Session, ctx: Ctx, reminder_id: int) -> None:
    s.delete(get_reminder(s, ctx, reminder_id))
    s.commit()


# --- engine ---------------------------------------------------------------------------------------


def _ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def _label(type_: str, family: Family) -> str:
    return wording(family) if type_ == "nappy" else LABELS.get(type_, type_)


def _due(s: Session, r: Reminder, child: Child, family: Family, now: datetime) -> tuple[str, str, str] | None:
    """(dedupe_key, title, body) if the reminder must fire now."""
    tz = zone(family.timezone)
    local = now.astimezone(tz)
    if r.days and local.weekday() not in r.days:
        return None
    if r.daytime_only and is_night(child, local, early_minutes=0):
        return None
    if r.type == "sleep_alert":
        p = predict(s, child, tz, now)
        if p is None or not p["start"] - timedelta(minutes=r.interval_minutes or 0) <= now < p["end"]:
            return None
        last = s.scalar(select(Entry.id).where(Entry.child_id == child.id, Entry.type == "sleep")
                        .order_by(Entry.ended_at.desc()).limit(1))
        at = p["start"].astimezone(tz).strftime("%H:%M")
        return (f"r{r.id}:sleep:{last}", f"{child.name}: sleep window soon",
                f"The next sleep window starts at {at}.")
    label = _label(r.type, family)
    if r.mode == "in":
        last = s.scalar(select(Entry).where(Entry.child_id == child.id, Entry.type == r.type)
                        .order_by(Entry.started_at.desc()).limit(1))
        if last is None or now < last.started_at + timedelta(minutes=r.interval_minutes or 0):
            return None
        return (f"r{r.id}:e{last.id}", f"{child.name}: {label} time",
                f"The last {label} was {_ago(now - last.started_at)} ago.")
    for t in r.times:
        due = datetime.combine(local.date(), hm(t), tz)
        if due <= local < due + AT_GRACE:
            return (f"r{r.id}:{local.date().isoformat()}:{t}", f"{child.name}: {label} time",
                    f"Reminder for {label} at {t}.")
    return None


def tick(s: Session, now: datetime) -> int:
    """Fire all due reminders once. Returns the number of new notifications."""
    fired = 0
    rows = s.execute(
        select(Reminder, Child, Family).join(Child, Reminder.child_id == Child.id)
        .join(Family, Child.family_id == Family.id)
        .where(Reminder.enabled.is_(True), Child.archived.is_(False))
    ).all()
    for r, child, family in rows:
        try:
            due = _due(s, r, child, family, now)
            if due and notify(s, family.id, child.id, f"reminder:{r.type}", due[1], due[2], due[0]):
                fired += 1
        except Exception:
            s.rollback()
            log.exception("Reminder %s failed", r.id)
    return fired
