"""Milestone catalog (CDC "Learn the Signs. Act Early.") with the child's achieved flags."""

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import Entry
from . import Ctx
from .children import corrected, dev_age_months, get_child


@lru_cache
def _catalog(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.is_file() else []


def catalog() -> list[dict]:
    return _catalog(get_settings().bundled_data_dir / "milestones.json")


def milestones(s: Session, ctx: Ctx, child_id: int) -> dict:
    child = get_child(s, ctx, child_id)
    achieved = {}
    for e in s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.type == "milestone")
                       .order_by(Entry.started_at)):
        if e.data.get("key"):
            achieved.setdefault(e.data["key"], e.started_at)
    bands: dict[int, list] = {}
    for item in catalog():
        bands.setdefault(item["age_months"], []).append(
            {**{k: item[k] for k in ("key", "domain", "text", "source")},
             "achieved": item["key"] in achieved, "achieved_at": achieved.get(item["key"])}
        )
    local = utcnow().astimezone(ctx.tz)
    # M13: the corrected age (from the due date) until 2 years for a baby born early.
    return {"age_months": round(dev_age_months(child, local), 1), "corrected": corrected(child, local.date()),
            "bands": [{"age_months": m, "items": items} for m, items in sorted(bands.items())]}
