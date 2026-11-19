"""CSV export of all entries of a child."""

import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Entry
from . import Ctx
from .children import get_child

COLUMNS = ["id", "type", "started_at", "ended_at", "duration_minutes", "data", "notes", "source"]


def _cell(text: str) -> str:
    """Stop spreadsheet apps from running a note as a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_csv(s: Session, ctx: Ctx, child_id: int) -> tuple[str, str]:
    """Returns (filename, csv text). Times are local to the family, with offset."""
    child = get_child(s, ctx, child_id)
    tz = ctx.tz
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for e in s.scalars(select(Entry).where(Entry.child_id == child.id).order_by(Entry.started_at, Entry.id)):
        minutes = round((e.ended_at - e.started_at).total_seconds() / 60, 1) if e.ended_at else ""
        w.writerow([
            e.id, e.type, e.started_at.astimezone(tz).isoformat(),
            e.ended_at.astimezone(tz).isoformat() if e.ended_at else "", minutes,
            json.dumps(e.data, separators=(",", ":")), _cell(e.notes or ""), e.source,
        ])
    safe = "".join(c for c in child.name if c.isalnum()) or "child"
    return f"frecklebubby-{safe}.csv", out.getvalue()
