"""The app code gives the same answers as the research code that was scored.

(a) predict.legacy == services.sleep.legacy, and (c) predict.method_c == services.sleep.estimate, on a synthetic
database made through the app's own services (replay_app_db.make_synthetic). The norms here are made up.
"""

import json
from datetime import UTC, datetime, timedelta

import episodes
import norms as N
import numpy as np
import predict as P
import replay_app_db as R

MODEL = {"history_days": 7, "prior_weight": 2.0, "clock_weight": 0.75, "duration_prior_weight": 3}


def made_up_norms() -> dict:
    bands = []
    for lo, hi in N.bands():
        a = (lo + hi) / 2
        ww = {k: [0, 0, round(90 + a * 0.4 + 5 * i), 0, 0] for i, k in enumerate(("1", "2", "3", "4"))}
        ww["bedtime"] = [0, 0, round(130 + a * 0.5), 0, 0]
        bands.append({"min_days": lo, "max_days": hi, "ww": ww, "bedtime": [0, 0, 1150, 0, 0],
                      "night_span": [0, 0, 640, 0, 0],
                      "nap_minutes": {k: [0, 0, 50 + 5 * i, 0, 0] for i, k in enumerate(("1", "2", "3", "4"))}})
    thr = [[1000, 990, 980, 970, 960] for _ in bands]
    q = {"nap_0": [-0.5, 0.6], "nap_h": [-0.4, 0.6], "bedtime_0": [-0.6, 0.3], "bedtime_h": [-0.5, 0.2]}
    return {"bands": bands, "night_gap_minutes": 70, "source": {}, "transitions": {},
            "model": {**MODEL, "log_ratio_p10_p90": q, "bedtime_after": thr}}


def matrix(entries, birth: datetime, tz) -> np.ndarray:
    """Logged sleeps -> (day of age, 144, 1) fractions, NaN outside the logged days."""
    mins = []
    for a, b in entries:
        s, e = (int((x.astimezone(tz).replace(tzinfo=None) - birth).total_seconds() // 60) for x in (a, b))
        mins.append((s, e))
    first, last = mins[0][0] // 1440, mins[-1][1] // 1440
    m = np.zeros((last + 1) * 1440)
    for s, e in mins:
        m[s:e] = 1
    d = m.reshape(-1, 144, 10).mean(axis=2)
    d[:first] = np.nan
    return d[:, :, None]


def test_app_matches_research_code(tmp_path, monkeypatch):
    db, cid = R.make_synthetic(tmp_path)
    n = made_up_norms()
    path = tmp_path / "norms.json"
    path.write_text(json.dumps(n))
    monkeypatch.setenv("SLEEP_NORMS_PATH", str(path))
    from sqlalchemy import select

    from frecklebubby.config import get_settings
    from frecklebubby.db import SessionLocal
    from frecklebubby.models import Child, Entry
    from frecklebubby.services import sleep, zone

    get_settings.cache_clear()
    s = SessionLocal()
    child = s.get(Child, cid)
    tz = zone("Australia/Brisbane")
    rows = [(e.started_at, e.ended_at) for e in s.scalars(select(Entry).where(Entry.child_id == cid)
                                                          .order_by(Entry.started_at))]
    birth = datetime.combine(child.birthdate, datetime.min.time())
    monkeypatch.setattr(episodes, "night_gap", lambda eps: 70)
    _, days, events, _ = episodes.extract(matrix(rows, birth, tz))
    look = P.lookups(n["bands"])
    f = P.features(days, events, [0], look, [MODEL["history_days"]], procs=2)
    c = P.method_c(f, n["model"]["bedtime_after"], MODEL["prior_weight"], MODEL["clock_weight"], "clock",
                   MODEL["duration_prior_weight"])
    first = f.day.min()
    checked = mismatched = 0
    for r, p in zip(f.itertuples(), c.itertuples(), strict=True):
        if r.day < first + 3:
            continue
        now = (birth + timedelta(days=int(r.day), minutes=int(r.wake_at) + 1)).replace(tzinfo=tz).astimezone(UTC)
        got = sleep.estimate(s, child, tz, now, sleep.norms())
        assert got is not None
        mid = got["start"] + timedelta(minutes=15)
        app_min = (mid.astimezone(tz).replace(tzinfo=None) - birth).total_seconds() / 60 - r.day * 1440
        checked += 1
        ok = (got["kind"] == "bedtime") == bool(p.bed) and abs(app_min - p.pred) < 1.5 and abs(
            got["duration_minutes"] - p.dur) < 1.5
        mismatched += not ok
    assert checked > 80 and mismatched == 0

    # (a): the research copy of the old method gives the old app answer.
    eps = [(int((a.astimezone(tz).replace(tzinfo=None) - birth).total_seconds() // 60),
            int((b.astimezone(tz).replace(tzinfo=None) - birth).total_seconds() // 60)) for a, b in rows]
    bands = json.loads((sleep.PACKAGE_DATA / "wake_windows.json").read_text())["wake_windows"]["bands"]
    for wake in [e for _, e in eps][5::7]:
        now = (birth + timedelta(minutes=wake + 1)).replace(tzinfo=tz).astimezone(UTC)
        old = sleep.legacy(s, child, tz, now)
        new = P.legacy([x for x in eps if x[1] <= wake], wake + 1, (wake + 1) // 1440, bands)
        if old is None:
            assert new is None
            continue
        start = (old["start"].astimezone(tz).replace(tzinfo=None) - birth).total_seconds() / 60
        # The app uses seconds, this copy whole minutes: up to 1 minute apart.
        assert old["kind"] == new["kind"] and abs(old["wake_window_minutes"] - new["ww"]) <= 1
        assert abs(start - new["start"]) < 2
    s.close()
