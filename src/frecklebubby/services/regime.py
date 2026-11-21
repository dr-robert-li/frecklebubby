"""The day and night plan (0.6.0): one typical 24 hours for a child, from a calculation and not from the AI model.

Order of the data:
1. The child's own logs of the last 14 days decide. With MIN_OWN complete days or more, only the child's own
   median is used. A median, because one bad night must not move the plan (sleep data has a long tail).
2. With fewer days, the own median is mixed with the value for the age (weight = days / MIN_OWN).
3. With no logs, the value for the age is used: the Liu et al. norms file to 24 months, then the published
   tables in data/sleep_regime.json.

The values for the age never limit the child's own values. They are shown as "common for the age" only.
"""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PACKAGE_DATA
from ..db import utcnow
from ..models import Child, Entry
from .children import hm
from .sleep import DAY, _recent, band, nights, norms, p50, recommendations, sleep_days, wake_range

DAYS = 14
MIN_OWN = 5  # complete days (or nights) from which the child's own median is used alone
MIN_ROWS = 3  # nights with the same number of feeds or wakes that are necessary to give clock times
FEEDS = ("nursing", "bottle")
LIU = "liu19"


@lru_cache
def table() -> dict:
    return json.loads((PACKAGE_DATA / "sleep_regime.json").read_text())


def published(months: float) -> dict:
    bands = table()["bands"]
    return next((b for b in bands if b["min_months"] <= months and (b["max_months"] is None or months < b["max_months"])),
                bands[-1])


def pct(xs: list[float], q: float) -> float:
    """Percentile with linear interpolation (q from 0 to 1)."""
    xs = sorted(xs)
    i = q * (len(xs) - 1)
    lo = int(i)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo)


def mode(xs: list[int]) -> int:
    return max(sorted(set(xs)), key=xs.count)


def blend(own: list[float], age: float | None) -> dict | None:
    """One value from the child's own samples and the value for the age. The own samples come first."""
    k = len(own)
    if not k and age is None:
        return None
    if k >= MIN_OWN or (k and age is None):
        value, basis = median(own), "own"
    elif k:
        w = k / MIN_OWN
        value, basis = w * median(own) + (1 - w) * age, "mixed"
    else:
        value, basis = age, "age"
    out = {"value": value, "basis": basis, "samples": k}
    if k >= MIN_OWN:  # the child's own usual range: 8 in 10 of the days
        out["low"], out["high"] = pct(own, 0.1), pct(own, 0.9)
    return out


def clock(minutes: float) -> str:
    m = round(minutes / 5) * 5 % DAY
    return f"{m // 60:02d}:{m % 60:02d}"


def hours(minutes: float) -> str:
    h = round(minutes / 6) / 10
    return f"{h:g} hours" if h != 1 else "1 hour"


class Age:
    """The values for the age: the norms file (Liu et al., to 24 months), else the published table."""

    def __init__(self, age_days: int, months: float):
        self.n = norms()
        self.b = band(self.n, age_days) if self.n else None
        self.pub = published(months)
        self.months = months
        self.used: list[str] = []

    def cite(self, key: str) -> None:
        if key not in self.used:
            self.used.append(key)

    def liu(self, field: str, key: str | None = None) -> float | None:
        if self.b is None:
            return None
        v = p50(self.n, self.b, field, key)
        if v is not None:
            self.cite(LIU)
        return v

    def value(self, field: str, key: str | None = None) -> float | None:
        v = self.liu(field, key)
        if v is None and (row := self.pub.get(field)) and isinstance(row, dict):
            self.cite(row["cite"])
            return row["mean"]
        return v

    def naps(self) -> int:
        if self.b is not None and (share := self.n["bands"][self.b].get("naps_share")):
            self.cite(LIU)
            return int(max(share, key=share.get))
        return self.pub.get("naps", 1)

    def common(self, field: str) -> tuple[float, float, str] | None:
        """The range that is common for the age: (low, high, source key)."""
        row = self.pub.get(field)
        if isinstance(row, dict) and "low" in row:
            return row["low"], row["high"], row.get("range_cite", row["cite"])
        if self.b is not None and (v := self.n["bands"][self.b].get(field)):
            return v[0], v[-1], LIU
        return None


def _nights(eps, nts, feeds: list[int], now_min: int) -> list[dict]:
    """One record for each complete night of the last DAYS days. Times are minutes after 00:00 of the evening."""
    out = []
    for d, idx in sorted(nts.items()):
        if d < -DAYS or now_min < (d + 1) * DAY + 8 * 60:  # tonight, or last night before 08:00: not complete
            continue
        start, end = eps[idx[0]][0], eps[idx[-1]][1]
        out.append({
            "day": d, "start": start - d * DAY, "end": end - d * DAY,
            "wakes": [eps[i][1] - d * DAY for i in idx[:-1]],
            "feeds": [f - d * DAY for f in feeds if start + 10 <= f <= end - 10],
            "longest": max(eps[i][1] - eps[i][0] for i in idx),
            "sleep": sum(eps[i][1] - eps[i][0] for i in idx),
        })
    return out


def _rows(recs: list[dict], field: str) -> list[float]:
    """Clock times for the usual night feeds or wakes: the nights with the most common count, by position."""
    if len(recs) < MIN_ROWS:
        return []
    k = mode([len(r[field]) for r in recs])
    same = [r[field] for r in recs if len(r[field]) == k]
    if not k or len(same) < MIN_ROWS:
        return []
    return [median(x[i] for x in same) for i in range(k)]


def regime(s: Session, child: Child, tz, now: datetime | None = None) -> dict:
    now = now or utcnow()
    local = now.astimezone(tz)
    age_days = (local.date() - child.birthdate).days
    months = age_days / 30.4375
    age = Age(age_days, months)
    name = child.name

    eps, _ = _recent(s, child, tz, now, DAYS + 2)
    nts = nights(eps, age.n["night_gap_minutes"] if age.n else 70)
    days = [d for d in sleep_days(eps, nts) if d["day"] >= -DAYS]
    origin = datetime.combine(local.date(), datetime.min.time())
    feeds = [int((t.astimezone(tz).replace(tzinfo=None) - origin).total_seconds() // 60) for t in s.scalars(
        select(Entry.started_at).where(Entry.child_id == child.id, Entry.type.in_(FEEDS),
                                       Entry.started_at >= now - timedelta(days=DAYS + 2)).order_by(Entry.started_at))]
    recs = _nights(eps, nts, feeds, local.hour * 60 + local.minute)

    # --- the day: wake, naps, bedtime ---------------------------------------------------------------------------------
    counts = [d["naps"] for d in days]
    recent = [d["naps"] for d in days if d["day"] >= -7]
    k = mode(recent) if len(recent) >= 4 else mode(counts) if len(counts) >= 3 else age.naps()
    kdays = [d for d in days if d["naps"] == k]
    cutoff = hm(child.morning_cutoff)
    profile_wake = cutoff.hour * 60 + cutoff.minute
    start = hm(child.night_start)
    profile_bed = start.hour * 60 + start.minute

    # No value for the age (a child older than the data): the times in the child's profile.
    wake = blend([d["ends"][0] - d["day"] * DAY for d in days], age.value("wake") or profile_wake)
    bed = blend([d["bedtime"] for d in days], age.value("bedtime") or profile_bed)
    lo, hi = wake_range(months)
    rows = [_row(wake, "wake", "Wake up", "day")]
    t = wake["value"]
    naps = []
    for i in range(k):
        key = str(min(i + 1, 4))
        ww = blend([d["starts"][i] - d["ends"][i] for d in kdays], age.liu("ww", key) or (lo + hi) / 2)
        length = blend([d["durations"][i] for d in kdays], age.value("nap_minutes", key) or 60)
        at = t + ww["value"]
        if at + length["value"] > bed["value"] - 30:  # no room before bedtime
            break
        own_starts = [d["starts"][i] - d["day"] * DAY for d in kdays]
        nap = {"value": at, "basis": ww["basis"], "samples": ww["samples"]}
        if len(own_starts) >= MIN_OWN:
            nap["low"], nap["high"] = pct(own_starts, 0.1), pct(own_starts, 0.9)
        r = _row(nap, "nap", f"Nap {i + 1}" if k > 1 else "Nap", "day")
        r["end"] = clock(at + length["value"])
        r["note"] = f"About {round(length['value'] / 5) * 5} minutes"
        rows.append(r)
        naps.append(length["value"])
        t = at + length["value"]
    rows.append(_row(bed, "bedtime", "Bedtime", "day"))

    # --- the night: feeds, wakes, longest sleep -----------------------------------------------------------------------
    pub = age.pub
    wakes_age = pub.get("night_wakes")
    feeds_age = pub.get("night_feeds")
    wakes = blend([len(r["wakes"]) for r in recs], wakes_age and wakes_age["p50"])
    night_feeds = blend([len(r["feeds"]) for r in recs], feeds_age and feeds_age["p50"])
    longest = blend([r["longest"] for r in recs], age.value("longest_night"))
    night_sleep = blend([r["sleep"] for r in recs], age.value("night_sleep"))
    for key in (wakes_age, feeds_age):
        if key:
            age.cite(key["cite"])
    feed_times = _rows(recs, "feeds")
    wake_times = [w for w in _rows(recs, "wakes") if all(abs(w - f) > 45 for f in feed_times)]
    night_rows = [(m, "night_feed", "Night feed") for m in feed_times] + [(m, "night_wake", "Night wake") for m in wake_times]
    for m, kind, label in sorted(night_rows):
        rows.append({"time": clock(m), "end": None, "kind": kind, "label": label, "part": "night", "basis": "own",
                     "earliest": None, "latest": None, "note": "A usual time in the last 14 days"})

    # --- facts: the child's own value next to the range that is common for the age --------------------------------------
    facts = []

    def fact(key: str, label: str, v: dict | None, field: str, fmt, count: bool = False) -> None:
        if v is None:
            return
        c = age.common(field)
        if c:
            age.cite(c[2])
        usual = None
        if "low" in v and round(v["low"], 1) != round(v["high"], 1):
            usual = f"{fmt(v['low'])} to {fmt(v['high'])}"
        value = v["value"]
        facts.append({"key": key, "label": label, "basis": v["basis"], "samples": v["samples"],
                      "value": fmt(round(value) if count and v["basis"] == "own" else value), "usual": usual,
                      "common": f"{fmt(c[0])} to {fmt(c[1])}" if c else None,
                      "outside": bool(c and v["basis"] == "own" and not c[0] <= value <= c[1])})

    num = lambda x: f"{x:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    day_sleep = sum(naps)
    if night_sleep:
        total = {**night_sleep, "value": night_sleep["value"] + day_sleep}
        total.pop("low", None)
        fact("total", "Sleep in 24 hours", total, "total", hours)
        fact("night_sleep", "Sleep at night", night_sleep, "night_sleep", hours)
    fact("longest", "Longest sleep at night", longest, "longest_night", hours)
    fact("wakes", "Wakes at night", wakes, "night_wakes", num, count=True)
    fact("feeds", "Feeds at night", night_feeds, "night_feeds", num, count=True)

    # --- notes: what the child's own data shows, then the rules for the age ---------------------------------------------
    notes: list[dict] = []
    own_days = len(days)
    if own_days >= MIN_OWN:
        basis = "own"
        notes.append({"text": f"This plan uses {name}'s own times from {own_days} of the last {DAYS} days. Each time is "
                              "the middle value, so one unusual day does not change the plan.", "cites": []})
    elif own_days:
        basis = "mixed"
        notes.append({"text": f"Only {own_days} complete day{'s' if own_days > 1 else ''} of sleep "
                              f"{'are' if own_days > 1 else 'is'} logged in the last {DAYS} days. The plan mixes {name}'s "
                              f"times with typical times for the age. From {MIN_OWN} days, it uses only {name}'s times.",
                      "cites": []})
    else:
        basis = "age"
        notes.append({"text": f"No complete day of sleep is logged in the last {DAYS} days. This plan shows typical "
                              f"times for the age. Log night sleep and naps, and the plan will use {name}'s own times.",
                      "cites": []})
    if len(counts) >= 4 and counts.count(k) / len(counts) < 0.7:
        other = mode([c for c in counts if c != k])
        notes.append({"text": f"{name} had {_naps(k)} on {counts.count(k)} of {len(counts)} days and {_naps(other)} on "
                              f"{counts.count(other)}. The number of naps is changing. This plan shows a day with "
                              f"{_naps(k)}.", "cites": []})
    if not feed_times and (feeds_age or months < 6):
        own_feeds = [len(r["feeds"]) for r in recs]
        if len(own_feeds) < MIN_ROWS:
            text = "Log the feeds at night, and the plan will show the usual times."
        elif median(own_feeds) < 0.5:
            text = f"{name} had no night feed on most of the last {len(own_feeds)} nights."
        else:
            text = f"{name}'s night feeds have no regular time yet, so the plan shows no clock times for them."
        notes.append({"text": text, "cites": []})
    if any(f["outside"] for f in facts):
        notes.append({"text": "A value outside the common range is not a problem by itself. Children differ a lot, and "
                              f"{name}'s own pattern is the reference for this plan. Speak to a doctor or nurse if you "
                              "are worried.", "cites": []})
    if bed.get("high") is not None and bed["high"] - bed["low"] > 90 and months >= 12:
        notes.append({"text": f"Bedtime moved by more than 90 minutes between days ({clock(bed['low'])} to "
                              f"{clock(bed['high'])}). A regular bedtime can help.", "cites": ["okely17"]})
    for r in recommendations(months)[-1:]:
        text = f"Recommended sleep in 24 hours for this age: {r['min_hours']:g} to {r['max_hours']:g} hours, naps included."
        notes.append({"text": text, "cites": [], "citation": r["citation"]})
    notes += [{"text": x["text"], "cites": list(x["cites"])} for x in pub["notes"]]

    # --- sources: a number for each one that the plan used ---------------------------------------------------------------
    for x in notes:
        for key in x["cites"]:
            age.cite(key)
    src = table()["sources"]
    sources = [{"n": i + 1, "kind": "link", **{a: b for a, b in src[key].items() if b}} for i, key in enumerate(age.used)]
    for x in notes:
        x["cites"] = [age.used.index(key) + 1 for key in x["cites"]]
        if c := x.pop("citation", None):
            sources.append({"n": len(sources) + 1, "kind": "link", **c})
            x["cites"] = [len(sources)]
    return {"age_band": pub["label"], "basis": basis, "own_days": own_days, "own_nights": len(recs), "days": DAYS,
            "naps": len(naps), "schedule": rows, "facts": facts, "notes": notes, "sources": sources}


def _row(v: dict, kind: str, label: str, part: str) -> dict:
    return {"time": clock(v["value"]), "end": None, "kind": kind, "label": label, "part": part, "basis": v["basis"],
            "earliest": clock(v["low"]) if "low" in v else None, "latest": clock(v["high"]) if "high" in v else None,
            "note": None}


def _naps(k: int) -> str:
    return "no nap" if k == 0 else "1 nap" if k == 1 else f"{k} naps"
