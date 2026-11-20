"""Children of a family."""

from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Child, ImportJob
from ..schemas import ChildIn, ChildPatch
from . import Conflict, Ctx, Invalid, NotFound, hm


def get_child(s: Session, ctx: Ctx, child_id: int) -> Child:
    child = s.get(Child, child_id)
    if child is None or child.family_id != ctx.fam.id:
        raise NotFound("Child not found.")
    return child


def list_children(s: Session, ctx: Ctx, include_archived: bool = False) -> list[Child]:
    q = select(Child).where(Child.family_id == ctx.fam.id).order_by(Child.id)
    if not include_archived:
        q = q.where(Child.archived.is_(False))
    return list(s.scalars(q))


def _check_birthdate(value: date) -> None:
    if value > date.today():
        raise Invalid("birthdate: must not be in the future")


EARLY_MAX = timedelta(weeks=20)  # a due date more than 20 weeks after the birth is a typing error


def _check_due(birthdate: date, due: date | None) -> None:
    if due is not None and not birthdate < due <= birthdate + EARLY_MAX:
        raise Invalid("due_date: give the due date of a baby born early: after the birth date, at most 20 weeks "
                      "after it")


def create_child(s: Session, ctx: Ctx, body: ChildIn) -> Child:
    _check_birthdate(body.birthdate)
    _check_due(body.birthdate, body.due_date)
    child = Child(family_id=ctx.fam.id, **body.model_dump())
    s.add(child)
    s.commit()
    return child


def update_child(s: Session, ctx: Ctx, child_id: int, body: ChildPatch) -> Child:
    child = get_child(s, ctx, child_id)
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "birthdate", "color", "night_start", "morning_cutoff", "archived"):
        if key in changes and changes[key] is None:
            raise Invalid(f"{key}: must not be null")
    if changes.get("birthdate"):
        _check_birthdate(changes["birthdate"])
    _check_due(changes.get("birthdate") or child.birthdate, changes.get("due_date", child.due_date))
    for key, value in changes.items():
        setattr(child, key, value)
    s.commit()
    return child


def archive_child(s: Session, ctx: Ctx, child_id: int) -> None:
    get_child(s, ctx, child_id).archived = True
    s.commit()


def delete_child(s: Session, ctx: Ctx, child_id: int, confirm: str) -> None:
    """The owner deletes one child and all its data for good. confirm must be the child's name. The foreign keys
    cascade from child: entries, timers, reminders, notifications, chats, the sleep plan and the support report."""
    ctx.require_owner()
    child = get_child(s, ctx, child_id)
    if confirm.strip().casefold() != child.name.strip().casefold():
        raise Invalid("confirm: type the child's name to delete the child.")
    from ..importer.huckleberry import _recover

    _recover(s)
    if s.scalar(select(ImportJob.id).where(ImportJob.family_id == ctx.fam.id,
                                           ImportJob.status.in_(("pending", "running")))):
        raise Conflict("An import is running. Wait until it is done, then try again.")
    s.execute(delete(Child).where(Child.id == child.id))
    s.commit()


def resolve_child(s: Session, ctx: Ctx, ref: str | int | None) -> Child:
    """Child by id or name (case-insensitive); None works when the family has one child."""
    children = list_children(s, ctx)
    if ref is None:
        if len(children) == 1:
            return children[0]
        if not children:
            raise NotFound("The family has no children. Add a child first.")
        raise Invalid(f"Say which child: {', '.join(c.name for c in children)}")
    wanted = str(ref).strip().lower()
    matches = [c for c in children if wanted in (str(c.id), c.name.lower())]
    if len(matches) == 1:
        return matches[0]
    raise NotFound(f"No single child matches {ref!r}. Children: {', '.join(c.name for c in children) or 'none'}")


def age_months(child: Child, at: datetime) -> float:
    return (at.date() - child.birthdate).days / 30.4375


def is_night(child: Child, local: datetime, early_minutes: int = 60) -> bool:
    """Night if the local time is between night_start − early_minutes and morning_cutoff (across midnight)."""
    start = hm(child.night_start)
    begin = (start.hour * 60 + start.minute - early_minutes) % 1440
    cutoff = hm(child.morning_cutoff)
    end = cutoff.hour * 60 + cutoff.minute
    t = local.hour * 60 + local.minute
    return (begin <= t or t < end) if begin > end else begin <= t < end


def corrected(child: Child, day: date) -> bool:
    """True when development uses the corrected age: a due date is set and the child is under 2 years (NHS and AAP:
    library file corrected-age-premature)."""
    b = child.birthdate
    return child.due_date is not None and (day.year, day.month, day.day) < (b.year + 2, b.month, b.day)


def dev_age_days(child: Child, day: date) -> int:
    """Age in days for development windows, milestone bands and the band notification: from the due date (the
    corrected age) until 2 years when a due date is set; else from the birth date. Never below 0."""
    return max(0, (day - (child.due_date if corrected(child, day) else child.birthdate)).days)


def dev_age_months(child: Child, at: datetime) -> float:
    return dev_age_days(child, at.date()) / 30.4375
