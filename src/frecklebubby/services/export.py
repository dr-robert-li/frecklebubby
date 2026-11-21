"""CSV export of the entries of a child: all of them, or the same selection as the entry list."""

import csv
import io
import json

from sqlalchemy.orm import Session

from . import Ctx
from .children import get_child
from .entries import list_entries

COLUMNS = ["id", "type", "started_at", "ended_at", "duration_minutes", "data", "notes", "source"]


def _cell(text: str) -> str:
    """Stop spreadsheet apps from running a note as a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_csv(s: Session, ctx: Ctx, child_id: int, **select) -> tuple[str, str]:
    """Returns (filename, csv text). Times are local to the family, with offset. `select` are the filter and
    order arguments of list_entries; with none, all entries, the oldest first."""
    child = get_child(s, ctx, child_id)
    tz = ctx.tz
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for e in list_entries(s, ctx, child.id, **{"newest_first": False, **select, "limit": None}):
        minutes = round((e.ended_at - e.started_at).total_seconds() / 60, 1) if e.ended_at else ""
        w.writerow([
            e.id, e.type, e.started_at.astimezone(tz).isoformat(),
            e.ended_at.astimezone(tz).isoformat() if e.ended_at else "", minutes,
            json.dumps(e.data, separators=(",", ":")), _cell(e.notes or ""), e.source,
        ])
    safe = "".join(c for c in child.name if c.isalnum()) or "child"
    return f"frecklebubby-{safe}.csv", out.getvalue()
