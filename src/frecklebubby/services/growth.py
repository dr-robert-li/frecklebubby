"""Growth points with WHO percentiles (LMS method) and reference curves."""

import csv
import math
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Entry
from . import Ctx
from .children import age_months, get_child

MEASURES = {"weight": ("weight", "weight_kg"), "height": ("length", "height_cm"), "head": ("head", "head_cm")}
CURVE_Z = {"p3": -1.880794, "p15": -1.036433, "p50": 0.0, "p85": 1.036433, "p97": 1.880794}


@lru_cache
def _table(path: Path) -> list[tuple[float, float, float, float]]:
    """Rows (age_months, L, M, S); empty when the file is missing."""
    if not path.is_file():
        return []
    with path.open() as f:
        return sorted((float(r["age_months"]), float(r["L"]), float(r["M"]), float(r["S"])) for r in csv.DictReader(f))


def _lms_table(measure: str, sex: str):
    return _table(get_settings().bundled_data_dir / "growth" / f"{MEASURES[measure][0]}_{sex}.csv")


def _lms_at(rows, months: float) -> tuple[float, float, float] | None:
    """Linear interpolation between whole months; None outside the table."""
    if not rows or not rows[0][0] <= months <= rows[-1][0]:
        return None
    i = bisect_right([r[0] for r in rows], months)
    if i >= len(rows):
        return rows[-1][1:]
    a, b = rows[i - 1], rows[i]
    f = (months - a[0]) / (b[0] - a[0])
    return tuple(a[k] + f * (b[k] - a[k]) for k in (1, 2, 3))  # type: ignore[return-value]


def percentile(x: float, lms: tuple[float, float, float]) -> float:
    # shortcut: no WHO restricted-tail adjustment beyond |z| > 3; add it if extreme values matter.
    L, M, S = lms
    z = ((x / M) ** L - 1) / (L * S) if L != 0 else math.log(x / M) / S
    return round(50 * (1 + math.erf(z / math.sqrt(2))), 1)


def _value(z: float, lms: tuple[float, float, float]) -> float:
    L, M, S = lms
    return round(M * (1 + L * S * z) ** (1 / L) if L != 0 else M * math.exp(S * z), 3)


def growth(s: Session, ctx: Ctx, child_id: int) -> dict:
    child = get_child(s, ctx, child_id)
    entries = s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.type == "growth")
                        .order_by(Entry.started_at))
    points = []
    for e in entries:
        months = age_months(child, e.started_at.astimezone(ctx.tz))
        p = {"entry_id": e.id, "at": e.started_at, "age_months": round(months, 2)}
        for measure, (_, field) in MEASURES.items():
            value = e.data.get(field)
            if value is None:
                continue
            p[field] = value
            lms = _lms_at(_lms_table(measure, child.sex), months) if child.sex else None
            p[f"{measure}_percentile"] = percentile(value, lms) if lms else None
        points.append(p)
    curves = {}
    if child.sex:
        for measure in MEASURES:
            curves[measure] = [
                {"age_months": int(r[0]), **{k: _value(z, r[1:]) for k, z in CURVE_Z.items()}}
                for r in _lms_table(measure, child.sex)
            ]
    return {"sex": child.sex, "points": points, "curves": curves}
