"""Sleep prediction (spec section 8, M7) and total sleep recommendations.

With a norms file (SLEEP_NORMS_PATH, default DATA_DIR/sleep_norms.json; made by training/sleep): the child's recent
wake windows for the same nap position are blended with the median of babies of the same age, and bedtime also
uses the child's usual bedtime. The method and its measured error are in .planning/M7_SLEEP_RESULTS.md.
Without the file: the wake-window table in data/wake_windows.json (the method before M7).
"""

import json
import logging
import math
from datetime import datetime, time, timedelta
from functools import lru_cache
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA, get_settings
from ..db import utcnow
from ..models import Child, Entry, Timer
from .children import age_months, is_night

log = logging.getLogger(__name__)
MARGIN = timedelta(minutes=15)
DAY = 1440
MERGE_GAP, MIN_SLEEP = 10, 5  # the same episode rules as training/sleep/episodes.py


@lru_cache
def _table() -> dict:
    return json.loads((PACKAGE_DATA / "wake_windows.json").read_text())


def _matches(row: dict, months: float) -> bool:
    return row["min_months"] <= months and (row["max_months"] is None or months < row["max_months"])


def wake_range(months: float) -> tuple[int, int]:
    bands = _table()["wake_windows"]["bands"]
    row = next((b for b in bands if _matches(b, months)), bands[-1])
    return row["min_minutes"], row["max_minutes"]


def recommendations(months: float) -> list[dict]:
    """Recommended total sleep per 24 h for the age, one row per source (AASM 2016, NSF 2015)."""
    return [{k: r[k] for k in ("min_hours", "max_hours", "citation")}
            for r in _table()["total_sleep"] if _matches(r, months)]


# --- norms file ---------------------------------------------------------------------------------------------------

@lru_cache
def _load(path: str, mtime: float) -> dict | None:
    try:
        n = json.loads(open(path, encoding="utf-8").read())
        assert n["bands"] and n["model"]["bedtime_after"] and n["night_gap_minutes"] > 0
        assert len(n["model"]["bedtime_after"]) == len(n["bands"])
        return n
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
        log.warning("Sleep norms file %s not used: %r", path, e)
        return None


def norms() -> dict | None:
    """The optional norms file, or None (then the app uses the old wake-window table)."""
    st = get_settings()
    path = st.sleep_norms_path or st.data_dir / "sleep_norms.json"
    try:
        return _load(str(path), path.stat().st_mtime)
    except OSError:
        return None


def band(n: dict, age_days: int) -> int | None:
    """Index of the age band, None outside the data (0 to 24 months)."""
    return next((i for i, b in enumerate(n["bands"]) if b["min_days"] <= age_days < b["max_days"]), None)


def p50(n: dict, b: int, field: str, key: str | None = None) -> float | None:
    """Median for the band; a band without a value uses the nearest band that has one."""
    for i in sorted(range(len(n["bands"])), key=lambda j: abs(j - b)):
        v = n["bands"][i].get(field)
        v = v.get(key) if key and v else v
        if v:
            return v[2]
    return None


# --- episodes and sleep-days (plain Python copy of training/sleep/episodes.py) --------------------------------------

def episodes_from(pairs, tz, now: datetime) -> tuple[list[list[int]], datetime]:
    """(start, end) UTC pairs in start order -> merged episodes in local clock minutes from today 00:00 (naive)."""
    origin = datetime.combine(now.astimezone(tz).date(), time())
    out: list[list[int]] = []
    for a, b in pairs:
        s, e = (int((x.astimezone(tz).replace(tzinfo=None) - origin).total_seconds() // 60) for x in (a, b))
        if out and s - out[-1][1] <= MERGE_GAP:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [x for x in out if x[1] - x[0] >= MIN_SLEEP], origin


def nights(eps: list[list[int]], gap: int) -> dict[int, list[int]]:
    """Night d (d 19:00 to d+1 07:00): the episode with the largest overlap (60 min or more) and the episodes that
    start between 18:00 and 08:00 within `gap` minutes of wake of it."""
    out: dict[int, list[int]] = {}
    if not eps:
        return out
    for d in range(eps[0][0] // DAY - 1, eps[-1][1] // DAY + 1):
        w0, w1 = d * DAY + 19 * 60, (d + 1) * DAY + 7 * 60
        ov = [min(e, w1) - max(s, w0) for s, e in eps]
        a = max(range(len(eps)), key=ov.__getitem__)
        if ov[a] < 60:
            continue
        i = j = a
        while i > 0 and eps[i][0] - eps[i - 1][1] <= gap and eps[i - 1][0] >= d * DAY + 18 * 60:
            i -= 1
        while j + 1 < len(eps) and eps[j + 1][0] - eps[j][1] <= gap and eps[j + 1][0] < (d + 1) * DAY + 8 * 60:
            j += 1
        out[d] = list(range(i, j + 1))
    return out


def sleep_days(eps: list[list[int]], nts: dict[int, list[int]]) -> list[dict]:
    """Sleep-day d = morning wake (end of night d-1) to bedtime (start of night d); sleeps between are naps.
    `ends[i]` -> `starts[i]` are the wake windows (the last one ends at bedtime)."""
    out = []
    for d, cur in sorted(nts.items()):
        prev = nts.get(d - 1)
        if prev is None or cur[0] <= prev[-1]:
            continue
        naps = eps[prev[-1] + 1:cur[0]]
        out.append({"day": d, "naps": len(naps), "bedtime": eps[cur[0]][0] - d * DAY,
                    "ends": [eps[prev[-1]][1]] + [e for _, e in naps], "starts": [s for s, _ in naps] + [eps[cur[0]][0]],
                    "durations": [e - s for s, e in naps] + [eps[cur[-1]][1] - eps[cur[0]][0]]})
    return out


def _recent(s: Session, child: Child, tz, now: datetime, days: int):
    rows = s.execute(select(Entry.started_at, Entry.ended_at).where(
        Entry.child_id == child.id, Entry.type == "sleep", Entry.ended_at.is_not(None),
        Entry.started_at >= now - timedelta(days=days), Entry.ended_at <= now).order_by(Entry.started_at))
    rows = list(rows)
    return episodes_from(rows, tz, now)[0], max((r[1] for r in rows), default=None)


def stage(s: Session, child: Child, tz, now: datetime, n: dict) -> dict | None:
    """Naps a day over the last 7 complete sleep-days (at least 4): {"naps": most common count, "days", "counts"}."""
    eps, _ = _recent(s, child, tz, now, 9)
    counts = [d["naps"] for d in sleep_days(eps, nights(eps, n["night_gap_minutes"])) if d["day"] >= -7]
    if len(counts) < 4:
        return None
    mode = max(sorted(set(counts)), key=counts.count)
    return {"naps": mode, "days": len(counts), "share": counts.count(mode) / len(counts)}


def age_summary(n: dict, age_days: int) -> str:
    """One line for the AI prompts: typical nap count, bedtime and wake windows for the age."""
    b = band(n, age_days)
    if b is None:
        return ""
    row = n["bands"][b]
    share = row.get("naps_share") or {}
    common = max(share, key=share.get) if share else None
    hh = lambda m: f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}"  # noqa: E731
    parts = [f"{common if common != '4' else '4 or more'} naps a day is most common"] if common else []
    if row.get("bedtime"):
        parts.append(f"bedtime {hh(row['bedtime'][1])} to {hh(row['bedtime'][3])} (middle half)")
    w1, wb = p50(n, b, "ww", "1"), p50(n, b, "ww", "bedtime")
    if w1 and wb:
        parts.append(f"wake window about {w1} min before the first nap and {wb} min before bedtime")
    return "Typical for this age in a research dataset of app users: " + "; ".join(parts) + "." if parts else ""


# --- prediction -----------------------------------------------------------------------------------------------------

def predict(s: Session, child: Child, tz, now: datetime | None = None, default: bool = False) -> dict | None:
    """Next sleep window. None while a sleep timer runs, or with no sleep in the last 24 h (unless default)."""
    now = now or utcnow()
    if s.scalar(select(Timer.id).where(Timer.child_id == child.id, Timer.type == "sleep")):
        return None
    n = norms()
    return estimate(s, child, tz, now, n, default=default) if n else legacy(s, child, tz, now, default)


def estimate(s: Session, child: Child, tz, now: datetime, n: dict, default: bool = False,
             history_days: int | None = None) -> dict | None:
    """The M7 method. Falls back to `legacy` when the day has no structure (no logged night in the last 24 h) or
    the child is older than the data (24 months). history_days=0 gives the age norms only (method b)."""
    m = n["model"]
    H = m["history_days"] if history_days is None else history_days
    eps, wake_at = _recent(s, child, tz, now, H + 3)
    nts = nights(eps, n["night_gap_minutes"])
    last = max(range(len(eps)), key=lambda i: eps[i][1], default=None)
    # The night that ended most recently: today's morning wake.
    night = max((d for d, idx in nts.items() if idx[0] <= (last or 0)), default=None)
    if (last is None or night is None or wake_at < now - timedelta(hours=24)
            or eps[last][1] - eps[nts[night][-1]][1] > 18 * 60):
        return legacy(s, child, tz, now, default)
    D = night + 1
    age = (now.astimezone(tz).date() - child.birthdate).days + D
    b = band(n, age)
    if b is None:  # shortcut: the data stops at 24 months; older children use the old table until there is data
        return legacy(s, child, tz, now, default)
    k = last - nts[night][-1]  # naps since the morning wake
    W = eps[last][1]
    hist = [d for d in sleep_days(eps, nts) if D - H <= d["day"] < D]

    lt = lambda x: x.astimezone(tz)  # noqa: E731

    def samples(key: str) -> tuple[float, int, float | None]:
        """Shrunk wake window and the child's median length for the next nap (key "1".."4") or bedtime."""
        lr, durs = [], []
        for d in hist:
            ref_b = band(n, age - (D - d["day"]))
            for i, (e, st) in enumerate(zip(d["ends"], d["starts"], strict=True)):
                ref = p50(n, b if ref_b is None else ref_b, "ww", key)
                if _key(i, len(d["starts"])) == key and st > e and ref:
                    lr.append(math.log((st - e) / ref))
                    durs.append(d["durations"][i])
        cnt = len(lr)
        shrink = cnt / (cnt + m["prior_weight"]) if cnt else 0
        return p50(n, b, "ww", key) * math.exp(shrink * (median(lr) if lr else 0)), cnt, median(durs) if durs else None

    thr = m["bedtime_after"][b][min(k, 4)]
    bed = (W - D * DAY) >= thr  # after this clock time, bedtime is more likely than another nap (train infants)
    key = "bedtime" if bed else str(min(k + 1, 4))
    ww, cnt, own_dur = samples(key)
    point = W + ww
    if bed and hist and m["clock_weight"]:
        f = m["clock_weight"] * len(hist) / (len(hist) + 1)
        point = (1 - f) * point + f * (D * DAY + median(d["bedtime"] for d in hist))
        point = max(point, W + 15)
    q = m["log_ratio_p10_p90"][f"{'bedtime' if bed else 'nap'}_{'h' if hist else '0'}"]
    ww = max(point - W, 5)
    start = wake_at + timedelta(minutes=point - W) - MARGIN
    # Night waking (woke in the night, next window also in the night): the child sleeps again the same night.
    if is_night(child, lt(wake_at), 0) and is_night(child, lt(start), 0):
        return None
    norm_dur = p50(n, b, "night_span") if bed else p50(n, b, "nap_minutes", key)
    kd = m["duration_prior_weight"]
    dur = norm_dur if own_dur is None else (cnt * own_dur + kd * norm_dur) / (cnt + kd)
    lo, hi = wake_range(age_months(child, now))
    days_word = f"{len(hist)} day" + ("s" if len(hist) != 1 else "")
    return {
        "start": start, "end": start + 2 * MARGIN, "kind": "bedtime" if bed else "nap",
        "basis": "personal" if cnt else "age", "wake_window_minutes": round(point - W), "samples": cnt,
        "age_range_minutes": (lo, hi),
        "note": (f"Based on your child's last {days_word} and typical patterns of babies this age in a research "
                 "dataset of app users. An estimate, not a medical standard.") if hist else
                ("Based on typical patterns of babies this age in a research dataset of app users. An estimate, "
                 "not a medical standard."),
        "earliest": wake_at + timedelta(minutes=ww * math.exp(q[0])),
        "latest": wake_at + timedelta(minutes=ww * math.exp(q[1])),
        "nap_index": None if bed else k + 1, "method": "personal_blend" if cnt else "age_norm",
        # shortcut: confidence from the number of own samples, not from a per-child error; see M7_SLEEP_RESULTS.md
        "confidence": "high" if cnt >= 3 else "medium" if cnt else "low",
        "duration_minutes": round(dur) if dur else None, "history_days": len(hist),
    }


def _key(i: int, n_starts: int) -> str:
    """Wake window i of a sleep-day: before nap i+1 ("4" = 4th or later) or, the last one, before bedtime."""
    return "bedtime" if i == n_starts - 1 else str(min(i + 1, 4))


def legacy(s: Session, child: Child, tz, now: datetime, default: bool = False) -> dict | None:
    """The method before M7: wake-window table by age, median of the last 7 days, clamped."""
    lo, hi = wake_range(age_months(child, now))
    note = _table()["wake_windows"]["note"]
    sleeps = list(s.scalars(
        select(Entry).where(Entry.child_id == child.id, Entry.type == "sleep", Entry.ended_at.is_not(None),
                            Entry.started_at >= now - timedelta(days=8), Entry.ended_at <= now)
        .order_by(Entry.started_at)
    ))
    last = max(sleeps, key=lambda e: e.ended_at, default=None)
    if last is None or last.ended_at < now - timedelta(hours=24):
        if not default:
            return None
        ww = (lo + hi) // 2
        start = now + timedelta(minutes=ww) - MARGIN
        end = start + 2 * MARGIN
        return {"start": start, "end": end, "kind": "bedtime" if is_night(child, end.astimezone(tz)) else "nap",
                "basis": "age", "wake_window_minutes": ww, "samples": 0, "age_range_minutes": (lo, hi), "note": note,
                "method": "wake_window_table"}

    # Wake windows before each sleep, tagged with the nap number since the last night sleep.
    samples: list[tuple[int, float]] = []
    position = 0
    since = now - timedelta(days=7)
    prev = None
    for e in sleeps:
        night = is_night(child, e.started_at.astimezone(tz))
        if prev is not None and e.started_at >= since:
            gap = (e.started_at - prev[0].ended_at).total_seconds() / 60
            if gap > 0 and not (night and prev[1]):  # night to night is a night waking, not a wake window
                samples.append((position, gap))
        position = 0 if night else position + 1
        prev = (e, night)

    same = [g for p, g in samples if p == position]
    if len(same) >= 3:
        ww, basis, used = median(same), "personal", len(same)
    elif len(samples) >= 3:
        ww, basis, used = median(g for _, g in samples), "personal", len(samples)
    else:
        ww, basis, used = (lo + hi) / 2, "age", 0
    ww = round(min(max(ww, lo), hi))
    start = last.ended_at + timedelta(minutes=ww) - MARGIN
    end = start + 2 * MARGIN
    # A night waking (woke in the night, next window also in the night): the child sleeps again the same night.
    if is_night(child, last.ended_at.astimezone(tz), 0) and is_night(child, start.astimezone(tz), 0):
        return None
    kind = "bedtime" if is_night(child, end.astimezone(tz)) else "nap"
    return {"start": start, "end": end, "kind": kind, "basis": basis, "wake_window_minutes": ww,
            "samples": used, "age_range_minutes": (lo, hi), "note": note, "method": "wake_window_table"}
