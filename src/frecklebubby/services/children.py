"""Children of a family."""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child
from ..schemas import ChildIn, ChildPatch
from . import Ctx, Invalid, NotFound, hm


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


def create_child(s: Session, ctx: Ctx, body: ChildIn) -> Child:
    _check_birthdate(body.birthdate)
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
    for key, value in changes.items():
        setattr(child, key, value)
    s.commit()
    return child


def archive_child(s: Session, ctx: Ctx, child_id: int) -> None:
    get_child(s, ctx, child_id).archived = True
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
