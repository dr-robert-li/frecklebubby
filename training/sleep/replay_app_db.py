"""Replay one child's history from a Frecklebubby database and score the next-sleep predictors.

Usage:
  python replay_app_db.py DB_FILE CHILD [--norms PATH]   score a real database (opened read-only)
  python replay_app_db.py --make-synthetic DB_DIR         make a test database with the app's own service functions

CHILD is the child id or name. For each wake in a complete sleep-day (a morning wake or the end of a nap, see
episodes.py), the script asks each method at the wake time what the next sleep is, and compares with the logged
next sleep. Methods: a = the app before M7 (wake-window table), b = age norms only (history 0 days), c = the M7
method (child's recent days blended with the norms). Running timers are ignored.
"""

import argparse
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean, median


def _session_ro(db: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///file:{db.resolve()}?mode=ro&uri=true", connect_args={"uri": True})
    return Session(engine)


def replay(db: Path, child_ref: str, norms_path: Path | None = None) -> dict:
    if norms_path:
        os.environ["SLEEP_NORMS_PATH"] = str(norms_path)
    from sqlalchemy import select

    from frecklebubby.config import get_settings
    from frecklebubby.models import Child, Entry, Family
    from frecklebubby.services import sleep, zone

    get_settings.cache_clear()
    n = sleep.norms()
    if n is None:
        sys.exit("No norms file: set --norms or SLEEP_NORMS_PATH.")
    s = _session_ro(db)
    child = next((c for c in s.scalars(select(Child)) if child_ref in (str(c.id), c.name)), None)
    if child is None:
        sys.exit(f"No child {child_ref!r}")
    tz = zone(s.get(Family, child.family_id).timezone)
    entries = list(s.scalars(select(Entry).where(Entry.child_id == child.id, Entry.type == "sleep",
                                                 Entry.ended_at.is_not(None)).order_by(Entry.started_at)))
    if not entries:
        sys.exit("No sleep entries.")
    last = entries[-1].ended_at
    eps, origin = sleep.episodes_from([(e.started_at, e.ended_at) for e in entries], tz, last)
    nights = sleep.nights(eps, n["night_gap_minutes"])
    rows: dict[str, list] = {"a": [], "b": [], "c": []}
    for d in sleep.sleep_days(eps, nights):
        for i, (w, st) in enumerate(zip(d["ends"], d["starts"], strict=True)):
            kind = "bedtime" if i == len(d["starts"]) - 1 else "nap"
            # Whole minutes here; the logged end has seconds, so ask one minute later to see the sleep that ended.
            now = (origin + timedelta(minutes=w + 1)).replace(tzinfo=tz).astimezone(UTC)
            actual = (origin + timedelta(minutes=st)).replace(tzinfo=tz).astimezone(UTC)
            preds = {"a": sleep.legacy(s, child, tz, now), "b": sleep.estimate(s, child, tz, now, n, history_days=0),
                     "c": sleep.estimate(s, child, tz, now, n)}
            for m, p in preds.items():
                if p is None:
                    rows[m].append(None)
                    continue
                mid = p["start"] + (p["end"] - p["start"]) / 2
                lo, hi = p.get("earliest", p["start"]), p.get("latest", p["end"])
                rows[m].append({"err": (mid - actual).total_seconds() / 60, "inside": lo <= actual <= hi,
                                "width": (hi - lo).total_seconds() / 60, "kind_ok": p["kind"] == kind,
                                "age_days": (now.astimezone(tz).date() - child.birthdate).days,
                                "hist": p.get("history_days", 0)})
    return {m: summary(r) for m, r in rows.items()}


def summary(rows: list) -> dict:
    ok = [r for r in rows if r]
    if not ok:
        return {"n": 0, "no_prediction": len(rows)}
    a = [abs(r["err"]) for r in ok]
    return {"n": len(ok), "no_prediction": len(rows) - len(ok), "median_ae": round(median(a), 1),
            "mae": round(mean(a), 1), "within_15": round(mean(x <= 15 for x in a), 3),
            "within_30": round(mean(x <= 30 for x in a), 3),
            "interval_coverage": round(mean(r["inside"] for r in ok), 3),
            "interval_width": round(median(r["width"] for r in ok), 1),
            "kind_accuracy": round(mean(r["kind_ok"] for r in ok), 3)}


def make_synthetic(db_dir: Path, days: int = 40, seed: int = 1) -> tuple[Path, int]:
    """A child of about 6 months with 3 naps, made through the app's services (with logging noise)."""
    os.environ["DATA_DIR"] = str(db_dir)
    from frecklebubby.config import get_settings
    from frecklebubby.db import SessionLocal, init_db
    from frecklebubby.schemas import ChildIn, EntryIn, FamilyIn
    from frecklebubby.services.children import create_child
    from frecklebubby.services.entries import create_entry
    from frecklebubby.services.families import context, create_family, sign_in

    get_settings.cache_clear()
    init_db(db_dir)
    g = random.Random(seed)
    s = SessionLocal()
    user = sign_in(s, "replay@example.com")
    create_family(s, context(s, user, "app"), FamilyIn(name="Replay", timezone="Australia/Brisbane"))
    ctx = context(s, user, "app")
    first = date(2026, 6, 1)
    child = create_child(s, ctx, ChildIn(name="Synth", birthdate=first - timedelta(days=180)))
    for i in range(days):
        if g.random() < 0.08:
            continue  # a day without logging
        day = datetime.combine(first + timedelta(days=i), datetime.min.time())
        t = day + timedelta(minutes=g.gauss(400, 20))  # morning wake about 06:40
        for nap in range(3):
            start = t + timedelta(minutes=g.gauss(130 + 10 * nap, 15))
            end = start + timedelta(minutes=max(20, g.gauss(55 - 10 * nap, 12)))
            create_entry(s, ctx, child.id, EntryIn(type="sleep", started_at=start, ended_at=end))
            t = end
        bed = max(t + timedelta(minutes=90), day + timedelta(minutes=g.gauss(1170, 15)))
        wake = day + timedelta(days=1, minutes=g.gauss(400, 20))
        mid = bed + timedelta(minutes=g.gauss(300, 30))  # one night waking of about 20 min
        create_entry(s, ctx, child.id, EntryIn(type="sleep", started_at=bed, ended_at=mid))
        create_entry(s, ctx, child.id, EntryIn(type="sleep", started_at=mid + timedelta(minutes=20), ended_at=wake))
    s.close()
    return db_dir / "frecklebubby.db", child.id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?")
    ap.add_argument("child", nargs="?")
    ap.add_argument("--norms", type=Path)
    ap.add_argument("--make-synthetic", type=Path, metavar="DB_DIR")
    a = ap.parse_args()
    if a.make_synthetic:
        db, cid = make_synthetic(a.make_synthetic)
        print(f"{db} child {cid}")
        return
    if not (a.db and a.child):
        ap.error("give DB_FILE and CHILD")
    for m, r in replay(Path(a.db), a.child, a.norms).items():
        print(m, r)


if __name__ == "__main__":
    main()
