"""The day and night plan: one typical 24 hours for a child as a timeline of sleep blocks and feeds. The app
calculates it; the AI model does not make the times.

1. The start point is the child's own logs of the last 14 days. Each time is a median, because one unusual day
   must not move the plan (sleep data has a long tail). With MIN_OWN complete days or more, only the child's own
   values are used. With fewer days they are mixed with the value for the age; with no logs the plan shows typical
   times for the age (the Liu et al. norms file to 24 months, then the published tables in data/sleep_regime.json).
2. Then small steps toward best practice. When the logs are outside a recommended range (too little sleep in 24
   hours; too few feeds for a young baby), the plan moves ONE small step toward the range and says what it changed.
   The next plan starts from the new logs, so the changes are gradual and follow what the family really does.

A baby younger than 12 weeks with no long night gets blocks from the hours in which the baby usually sleeps, not a
wake/nap/bedtime structure: the day and night rhythm forms at about 8 to 15 weeks.
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
from . import training
from .children import hm
from .sleep import DAY, _recent, band, nights, norms, p50, sleep_days, wake_range

DAYS = 14
MIN_OWN = 5  # complete days (or nights) from which the child's own median is used alone
MIN_ROWS = 3  # nights with the same number of feeds or wakes that are necessary to give clock times
RHYTHM_DAYS = 84  # 12 weeks: younger babies get the rhythm view, unless their logs show a long night already
FEEDS = ("nursing", "bottle")
FEED_GAP = 45  # minutes: feeds that start closer together count as one feed
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


def dur(minutes: float) -> str:
    return f"{round(minutes / 5) * 5} minutes" if minutes < 90 else hours(minutes)


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

    def common(self, field: str, key: str | None = None) -> tuple[float, float, str] | None:
        """The range that is common for the age: (low, high, source key)."""
        row = self.pub.get(field)
        if isinstance(row, dict) and "low" in row:
            return row["low"], row["high"], row.get("range_cite", row["cite"])
        if self.b is not None and (v := self.n["bands"][self.b].get(field)):
            v = v.get(key) if key else v
            if v:
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


STEP_MIN, STEP_MAX = 15, 60  # minutes of sleep that one plan adds: a quarter of the gap, inside these limits
BED_STEP = 20  # the most that one plan moves bedtime
NAP_STEP = 15  # the most that one plan makes a nap longer
NEW_SLEEP = (45, 90)  # length of a sleep block that one plan adds for a young baby
LONG_AWAKE = 150  # a young baby: a gap between sleep blocks from which the plan can add a block


def regime(s: Session, child: Child, tz, now: datetime | None = None) -> dict:
    """The plan for a child of the app: read the logs of the last days, then calculate."""
    now = now or utcnow()
    local = now.astimezone(tz)
    eps, _ = _recent(s, child, tz, now, DAYS + 2)
    origin = datetime.combine(local.date(), datetime.min.time())
    feeds = [int((t.astimezone(tz).replace(tzinfo=None) - origin).total_seconds() // 60) for t in s.scalars(
        select(Entry.started_at).where(Entry.child_id == child.id, Entry.type.in_(FEEDS),
                                       Entry.started_at >= now - timedelta(days=DAYS + 2)).order_by(Entry.started_at))]
    night0, night1 = (h.hour * 60 + h.minute for h in (hm(child.night_start), hm(child.morning_cutoff)))
    # Sleep training (an option, off by default): the plan takes no step at bedtime; bedtime fading sets bedtime.
    t = training.current(s, child)
    active = t is not None and t.status == "active"
    return calculate(child.name, (local.date() - child.birthdate).days, eps, feeds, local.hour * 60 + local.minute,
                     night0, night1, hold_bedtime=active,
                     bedtime=t.state.get("bedtime") if active and t.method == "fading" else None)


def calculate(name: str, age_days: int, eps: list[list[int]], feed_starts: list[int], now_min: int,
              night0: int = 19 * 60, night1: int = 7 * 60, hold_bedtime: bool = False,
              bedtime: float | None = None, steps: bool = True) -> dict:
    """The plan from plain data, with no database (training/sleep replays it on the research data).
    eps: merged sleep episodes [start, end] in local minutes from today 00:00 (the past is negative), in time order.
    feed_starts: the same clock, in time order. night0, night1: night start and morning start of the profile.
    steps=False gives the start point only (the child's own pattern), with no step toward best practice."""
    months = age_days / 30.4375
    age = Age(age_days, months)
    nts = nights(eps, age.n["night_gap_minutes"] if age.n else 70)
    days = [d for d in sleep_days(eps, nts) if d["day"] >= -DAYS]
    feeds: list[int] = []
    for m in feed_starts:
        if not feeds or m - feeds[-1] > FEED_GAP:  # the second side, or a top-up, is the same feed
            feeds.append(m)
    recs = _nights(eps, nts, feeds, now_min)
    facts: list[dict] = []
    notes: list[dict] = []
    fact = lambda *args, **kw: _fact(facts, age, *args, **kw)  # noqa: E731
    num = lambda x: f"{x:.1f}".rstrip("0").rstrip(".")  # noqa: E731

    spans = [r["end"] - r["start"] for r in recs]
    rhythm = age_days < RHYTHM_DAYS and (len(spans) < MIN_ROWS or median(spans) < 8 * 60)
    if rhythm:
        blocks, own_days, begin, own_total = _young(age, eps, night0, night1, facts)
        notes.append({"text": f"{name} is a young baby with no fixed day and night yet. The plan shows {name}'s usual "
                              f"number of sleeps, at the times of the day at which {name} sleeps most often."
                      if own_days >= MIN_ROWS and blocks and blocks[0]["basis"] == "own" else
                      f"{name} is a young baby with no fixed day and night yet. Too few days are logged, so the sleep "
                      "blocks are typical for the age.", "cites": ["wong22"]})
    else:
        blocks, own_days, begin, own_total = _older(name, age, days, recs, months, night0, night1, facts, notes)
    basis = "own" if own_days >= MIN_OWN else "mixed" if own_days else "age"
    if basis == "own" and not rhythm:
        notes.insert(0, {"text": f"The start point of this plan is {name}'s own times from {own_days} of the last {DAYS} "
                                 "days. Each time is the middle value, so one unusual day does not change the plan.",
                         "cites": []})
    elif basis == "mixed":
        notes.insert(0, {"text": f"Only {own_days} complete day{'s' if own_days > 1 else ''} of sleep "
                                 f"{'are' if own_days > 1 else 'is'} logged in the last {DAYS} days. The plan mixes "
                                 f"{name}'s times with typical times for the age. From {MIN_OWN} days, it starts from "
                                 f"{name}'s times only.", "cites": []})
    elif basis == "age":
        notes.insert(0, {"text": f"No complete day of sleep is logged in the last {DAYS} days. This plan shows typical "
                                 f"times for the age. Log the sleep, and the plan will start from {name}'s own times.",
                         "cites": []})

    # --- feeds: the usual times of the day and of the night, in the same timeline ---------------------------------------
    feed_rows, feed_count = _feeds(age, feeds, begin, months)
    in_night = lambda m: any(b["kind"] == "night" and b["start"] <= m < b["end"] for b in blocks) if not rhythm else (  # noqa: E731
        (m % DAY >= night0 or m % DAY < night1) if night0 > night1 else night0 <= m % DAY < night1)
    night_feeds = blend([len(r["feeds"]) for r in recs], (age.pub.get("night_feeds") or {}).get("p50")) if not rhythm else \
        blend([sum(1 for f in feeds if d * DAY + night0 <= f < (d + 1) * DAY + night1) for d in range(-DAYS, -1)
               if any(d * DAY <= f < (d + 2) * DAY for f in feeds)], None)
    if feed_count:
        fact("feeds_24h", "Feeds in 24 hours", feed_count, "feeds_24h", num, count=True, flag=False)
    fact("feeds", "Feeds at night", night_feeds, "night_feeds", num, count=True)
    if not feed_rows and months < 12:
        notes.append({"text": "Log the feeds, and the plan will show their usual times in the day and in the night.",
                      "cites": []})

    # --- does the plan fit the logs? ------------------------------------------------------------------------------------
    # The calculator knows two patterns: naps and a night, and (a young baby) sleeps round the clock. When the logs
    # do not fit, the plan must say so and take no steps. A confident wrong plan is worse than a rough guide.
    doubts = _doubts(rhythm, blocks, days, eps, own_days, own_total)
    if doubts:
        notes.insert(0, {"text": f"{name}'s logs do not show one regular pattern that the app can use: {doubts[0]} "
                                 "Read this plan as a rough guide. It takes no steps until the pattern is clearer.",
                         "cites": []})

    # --- small steps toward best practice ----------------------------------------------------------------------------
    nudges: list[dict] = []
    caveats: list[dict] = []
    bands = table()["sleep_bands"]
    b = next(x for x in bands["bands"] if x["min_months"] <= months and (x["max_months"] is None or months < x["max_months"]))
    words = f"{b['rec_low']} to {b['rec_high']} hours"
    if doubts:
        feed_count = feed_count and {**feed_count, "basis": "age"}
    if own_total is not None and basis != "age":
        says = f"{name}'s logs show about {hours(own_total)} of sleep in 24 hours."
        if (doubts or not steps) and own_total <= b["ok_high"] * 60:
            pass  # a rough guide: no steps. The check for very long sleep below is not a step, so it stays.
        elif own_total < b["rec_low"] * 60:
            # Too little sleep: a step up. Inside the "may be appropriate" band the step is the smallest one.
            inside = own_total >= b["ok_low"] * 60
            gap = b["rec_low"] * 60 - own_total
            step = STEP_MIN if inside else min(max(round(gap / 4 / 5) * 5, STEP_MIN), STEP_MAX)
            added = _more_sleep(blocks, step, rhythm, age, name, begin, hold_bedtime)
            if added:
                nudges.append({
                    "text": f"{says} The recommended range for this age is {words}. "
                            + (f"{b['ok_low']} hours or more can also be right for some children, so the step is small. "
                               if inside else "")
                            + f"This plan adds about {dur(added)} of sleep. The plan changes in small steps. When "
                              f"{name}'s logs follow, the next plan takes the next step.", "cites": [bands["cite"]]})
                caveats.append({"text": f"The app counts only the sleep that is logged. If {name} sleeps at times that "
                                        "are not logged, log them, and the plan needs fewer changes."
                                        + ("" if inside else f" Fewer than {b['ok_low']} hours of sleep in 24 hours is "
                                           "not recommended for this age. If the logs are complete, speak to a doctor "
                                           "or nurse."), "cites": [] if inside else [bands["cite"]]})
        elif own_total > b["ok_high"] * 60:
            # Much more sleep than recommended. No source says to cut the sleep of a healthy child: check, not cut.
            nudges.append({
                "text": f"{says} This is more than {b['ok_high']} hours, which is not recommended for this age. The plan "
                        f"does not cut sleep. First check the logs: a sleep timer that was not stopped gives too many "
                        f"hours. If the logs are right, speak to a doctor or nurse. Long sleep can be a sign of illness. "
                        f"See a doctor soon if {name} is hard to wake, is floppy, does not feed well, has fewer wet "
                        "nappies, or has yellow skin.", "cites": [bands["cite"]]})
        elif own_total > b["rec_high"] * 60:
            notes.append({"text": f"{says} This is more than the recommended range of {words}. Up to {b['ok_high']} "
                                  "hours can be right for some children, so the plan makes no change. Speak to a doctor "
                                  "or nurse if you are worried.", "cites": [bands["cite"]]})
    # From about 2 years: a long or late nap can move the night. One step down for the nap, when the night suffers.
    lim = table()["nap_limit"]
    naps_ = [x for x in blocks if x["kind"] == "nap"]
    night_ = next((x for x in blocks if x["kind"] == "night"), None)
    if steps and not doubts and not rhythm and basis != "age" and months >= lim["from_months"] and naps_ and night_:
        nap = naps_[-1]
        long_, late = nap["end"] - nap["start"] > lim["max_minutes"], nap["end"] > lim["latest_end"]
        usual_start = night_["start"] + (BED_STEP if night_.get("change") else 0)
        suffers = usual_start > lim["late_night_start"] or night_["end"] - usual_start < lim["short_night"]
        if (long_ or late) and suffers and not nap.get("change"):
            step = min(lim["step"], nap["end"] - nap["start"] - 45)
            if step >= 5:
                nap["change"] = f"Ends {step} minutes earlier than {name}'s usual {clock(nap['end'])}. Wake {name} gently."
                nap["end"] -= step
                nudges.append({
                    "text": f"{name}'s nap " + ("is longer than 2 hours" if long_ else f"ends after {clock(lim['latest_end'])}")
                            + f", and the night sleep starts late or is short. From about 2 years, a long or late nap can "
                              f"move the night sleep. This plan ends the nap {step} minutes earlier. A nap of 2 hours at "
                              f"most, with the child awake by {clock(lim['latest_end'])}, is the usual advice.",
                    "cites": list(lim["cites"])})
    feeds_age = age.pub.get("feeds_24h")
    if steps and feeds_age and feed_rows and feed_count and feed_count["basis"] != "age":
        new = []
        if feed_count["value"] < feeds_age["low"]:  # one more feed, in the longest time between two feeds
            new.append(_gap(feed_rows))
            nudges.append({"text": f"{name}'s logs show about {num(round(feed_count['value']))} feeds in 24 hours. Young "
                                   f"babies usually feed {feeds_age['low']} to {feeds_age['high']} times in 24 hours. "
                                   "This plan adds 1 feed, in the longest time between two feeds. Feed sooner when "
                                   f"{name} shows signs of hunger.", "cites": [feeds_age["cite"]]})
        if age_days < 28:  # the first weeks: no more than about 4 hours at night without a feed
            late = [g for g in _gaps(feed_rows + new) if g[1] - g[0] > 250 and in_night((g[0] + g[1]) / 2)]
            for a, b in late:
                new.append(_new_feed((a + b) / 2))
            if late:
                nudges.append({"text": "In the first weeks, do not let more than about 4 hours pass at night without a "
                                       "feed. This plan adds a feed in each longer time at night.",
                               "cites": [feeds_age["cite"]]})
        feed_rows += new

    night_block = next((x for x in blocks if x["kind"] == "night"), None)
    if bedtime is not None and night_block and not rhythm:
        night_block.setdefault("usual", night_block["start"])
        night_block["start"] = bedtime
        night_block["change"] = (f"Sleep training (bedtime fading): bedtime tonight. {name} usually falls asleep at "
                                 f"about {clock(night_block['usual'])}.")

    # A feed that the app placed (typical for the age, or new in this plan) does not go into a sleep block: it moves
    # to the end of the block. The child's own usual feed times stay as they are.
    for f in feed_rows:
        if f["basis"] != "own" or f["change"] or rhythm:
            for b in blocks:
                at = (f["at"] - b["start"]) % DAY + b["start"]
                if b["start"] <= at < b["end"] and (rhythm or b["kind"] != "night"):
                    f["at"] = b["end"] + 5
    feed_rows = [f for i, f in enumerate(feed_rows) if all(abs(f["at"] - g["at"]) > 20 for g in feed_rows[:i])]

    # --- the timeline: from the morning, sleep blocks and feeds in the order of the clock ------------------------------
    for f in feed_rows:
        f["part"] = "night" if in_night(f["at"]) else "day"
    rows = sorted([_block_row(b, name) for b in blocks] + [_feed_row(f) for f in feed_rows],
                  key=lambda r: ((r.pop("at") - begin) % DAY, r["kind"] == "feed"))
    return _finish(age, months, caveats + notes, {
        "mode": "rhythm" if rhythm else "clock", "basis": basis, "own_days": own_days, "own_nights": len(recs),
        "naps": sum(1 for b in blocks if b["kind"] != "night"), "schedule": rows, "facts": facts, "nudges": nudges,
        "confidence": "low" if doubts else "normal", "training": hold_bedtime,
        "usual_bedtime": night_block and night_block["basis"] != "age" and night_block.get("usual", night_block["start"])
        or None})


def _doubts(rhythm: bool, blocks: list[dict], days: list[dict], eps, own_days: int, own_total: float | None) -> list[str]:
    """Reasons for which the plan does not fit the logs. Empty: the plan fits."""
    out = []
    logged = sum(1 for e in eps if e[0] >= -DAYS * DAY)
    if rhythm:
        planned = sum(b["end"] - b["start"] for b in blocks)
        if own_days >= MIN_ROWS and own_total is not None and abs(planned - own_total) > 180:
            out.append("the sleep times are very different from day to day.")
        return out
    if not own_days and logged >= 6:
        out.append("the app does not find a night sleep in them. It looks for the main sleep between 19:00 and 07:00.")
    counts = [d["naps"] for d in days]
    if len(counts) >= 4 and max(counts.count(c) for c in set(counts)) / len(counts) < 0.4:
        out.append("the number of naps is very different from day to day.")
    night = blocks[-1]["end"] - blocks[-1]["start"]
    if own_days and not 6 * 60 <= night <= 15 * 60:
        out.append(f"the night sleep in the logs is about {hours(night)} long.")
    return out


def _older(name: str, age: Age, days, recs, months, night0, night1, facts, notes) -> tuple[list[dict], int, float, float | None]:
    """A child with a day and a night: naps and one night block, from the child's own medians."""
    fact = lambda *args, **kw: _fact(facts, age, *args, **kw)  # noqa: E731
    num = lambda x: f"{x:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    counts = [d["naps"] for d in days]
    recent = [d["naps"] for d in days if d["day"] >= -7]
    k = mode(recent) if len(recent) >= 4 else mode(counts) if len(counts) >= 3 else age.naps()
    kdays = [d for d in days if d["naps"] == k]
    # No value for the age (a child older than the data): the times in the child's profile.
    wake = blend([d["ends"][0] - d["day"] * DAY for d in days], age.value("wake") or night1)
    bed = blend([d["bedtime"] for d in days], age.value("bedtime") or night0)
    lo, hi = wake_range(months)
    blocks, t = [], wake["value"]
    for i in range(k):
        key = str(min(i + 1, 4))
        ww = blend([d["starts"][i] - d["ends"][i] for d in kdays], age.liu("ww", key) or (lo + hi) / 2)
        length = blend([d["durations"][i] for d in kdays], age.value("nap_minutes", key) or 60)
        at = t + ww["value"]
        if at + length["value"] > bed["value"] - 30:  # no room before bedtime
            break
        own_starts = [d["starts"][i] - d["day"] * DAY for d in kdays]
        b = {"start": at, "end": at + length["value"], "kind": "nap", "label": f"Nap {i + 1}" if k > 1 else "Nap",
             "basis": ww["basis"]}
        if len(own_starts) >= MIN_OWN:
            b["low"], b["high"] = pct(own_starts, 0.1), pct(own_starts, 0.9)
        blocks.append(b)
        t = b["end"]
    night = {"start": bed["value"], "end": wake["value"] + DAY, "kind": "night", "label": "Night sleep",
             "basis": bed["basis"] if bed["basis"] == wake["basis"] else "mixed"}
    if "low" in bed:
        night["low"], night["high"] = bed["low"], bed["high"]
    blocks.append(night)

    wakes_age = age.pub.get("night_wakes")
    if wakes_age:
        age.cite(wakes_age["cite"])
    wakes = blend([len(r["wakes"]) for r in recs], wakes_age and wakes_age["p50"])
    night_sleep = blend([r["sleep"] for r in recs], age.value("night_sleep"))
    day_sleep = sum(b["end"] - b["start"] for b in blocks[:-1])
    own_total = None
    if night_sleep:
        total = {**night_sleep, "value": night_sleep["value"] + day_sleep}
        total.pop("low", None)
        own_total = total["value"]
        fact("total", "Sleep in 24 hours", total, "total", hours)
        fact("night_sleep", "Sleep at night", night_sleep, "night_sleep", hours)
    fact("longest", "Longest sleep at night", blend([r["longest"] for r in recs], age.value("longest_night")),
         "longest_night", hours)
    fact("wakes", "Wakes at night", wakes, "night_wakes", num, count=True)
    if counts:  # the typical number only describes children of this age: no step toward it
        fact("naps", "Sleeps in the day", blend(counts, None), "naps", num, count=True, flag=False)

    if len(counts) >= 4 and counts.count(k) / len(counts) < 0.7:
        other = mode([c for c in counts if c != k])
        notes.append({"text": f"{name} had {_naps(k)} on {counts.count(k)} of {len(counts)} days and {_naps(other)} on "
                              f"{counts.count(other)}. The number of naps is changing. This plan shows a day with "
                              f"{_naps(k)}.", "cites": []})
    if any(f["outside"] for f in facts):
        notes.append({"text": "A value outside the range that is common for the age is not a problem by itself. "
                              "Children differ a lot. Speak to a doctor or nurse if you are worried.", "cites": []})
    if bed.get("high") is not None and bed["high"] - bed["low"] > 90 and months >= 12:
        notes.append({"text": f"Bedtime moved by more than 90 minutes between days ({clock(bed['low'])} to "
                              f"{clock(bed['high'])}). A regular bedtime can help.", "cites": ["okely17"]})
    return blocks, len(days), wake["value"] - 30, own_total


def _young(age: Age, eps, night0: int, night1: int, facts) -> tuple[list[dict], int, float, float | None]:
    """A young baby: sleep blocks from the half hours in which the baby was asleep on half of the logged days or more.
    With too few days: blocks that are typical for the age."""
    fact = lambda *args, **kw: _fact(facts, age, *args, **kw)  # noqa: E731
    at_night = lambda m: (m % DAY >= night0 or m % DAY < night1) if night0 > night1 else night0 <= m % DAY < night1  # noqa: E731
    eps = [e for e in eps if e[1] > -DAYS * DAY and e[0] < 0]
    logged = sorted({e[0] // DAY for e in eps if -DAYS <= e[0] // DAY < 0})
    gaps = [b[0] - a[1] for a, b in zip(eps, eps[1:], strict=False) if 10 <= b[0] - a[1] <= 240]  # longer: not logged
    # With no norms file: the wake-window table, and plain lengths for a young baby.
    awake = blend(gaps, age.liu("ww", "1") or sum(wake_range(age.months)) / 2)
    day_len = blend([e[1] - e[0] for e in eps if not at_night(e[0])], age.liu("nap_minutes", "1") or 60)
    night_len = blend([e[1] - e[0] for e in eps if at_night(e[0])], age.liu("longest_night") or 180)
    fact("awake", "Awake time between sleeps", awake, "ww", dur, sub="1")
    fact("day_sleep", "Length of a sleep in the day", day_len, "nap_minutes", dur, sub="1")
    fact("night_stretch", "Length of a sleep at night", night_len, None, dur)
    total = blend([sum(min(e[1], (d + 1) * DAY) - max(e[0], d * DAY) for e in eps if e[1] > d * DAY and e[0] < (d + 1) * DAY)
                   for d in logged], None)
    fact("total", "Sleep logged in 24 hours", total, "total", hours, flag=False)

    blocks: list[dict] = []
    if len(logged) >= MIN_ROWS:
        # The baby's usual number of sleeps in a day, at the times of the day at which the baby sleeps most often.
        # A young baby does not sleep at the same hours each day, so a fixed share of the days finds too few blocks.
        cover = [[(e, d * DAY + k * 30 + 15) for d in logged for e in eps
                  if min(e[1], d * DAY + (k + 1) * 30) - max(e[0], d * DAY + k * 30) >= 15] for k in range(48)]
        share = [len(c) / len(logged) for c in cover]
        smooth = [(share[k - 1] + 2 * share[k] + share[(k + 1) % 48]) / 4 for k in range(48)]
        # The usual number of sleeps is counted for the day and for the night separately. The sleeps of the day are
        # often at different hours from day to day; with one count for the 24 hours, the night would take all blocks.
        for night in (False, True):
            want = round(median(sum(1 for e in eps if e[0] // DAY == d and at_night(e[0]) == night) for d in logged))
            got = 0
            for k in sorted((k for k in range(48) if at_night(k * 30 + 15) == night), key=lambda k: -smooth[k]):
                if got >= want or not cover[k]:
                    continue
                first, last = (median(e[i] - c for e, c in cover[k]) for i in (0, 1))  # start and end, from the half hour
                start = (k * 30 + 15 + first - night1) % DAY + night1  # from the morning: after midnight comes last
                end = start + max(last - first, 20)
                # 30 minutes awake or more between two blocks, also over midnight
                if not any(start - 30 < b["end"] + s and b["start"] + s < end + 30 for b in blocks for s in (-DAY, 0, DAY)):
                    blocks.append({"start": start, "end": end, "basis": "own"})
                    got += 1
    if not blocks:  # typical for the age (or the baby's own lengths, no usual hours)
        t, end = night1, night1 + DAY
        while t + awake["value"] + 30 < end:
            start = t + awake["value"]
            length = (night_len if at_night(start) else day_len)["value"]
            blocks.append({"start": start, "end": min(start + length, end), "basis": "age" if not logged else "mixed"})
            t = blocks[-1]["end"]
    blocks.sort(key=lambda b: b["start"])
    for i, b in enumerate(blocks, 1):
        b.update(kind="night" if at_night(b["start"]) else "nap", label=f"Sleep {i}")
    return blocks, len(logged), night1, total and total["value"]


def _more_sleep(blocks: list[dict], step: int, rhythm: bool, age: Age, name: str, begin: float,
                hold_bedtime: bool = False) -> int:
    """Add about `step` minutes of sleep to the plan, in the way that fits the age. Returns the minutes added."""
    if rhythm:
        # A young baby: one new sleep block in the longest time awake between two blocks.
        if not blocks:
            return 0
        pairs = [(a, b) for a, b in zip(blocks, blocks[1:] + [{**blocks[0], "start": blocks[0]["start"] + DAY}], strict=True)]
        a, b = max(pairs, key=lambda p: p[1]["start"] - p[0]["end"], default=(None, None))
        gap = b["start"] - a["end"] if a else 0
        if gap < LONG_AWAKE:
            return 0
        length = min(max(step, NEW_SLEEP[0]), NEW_SLEEP[1], gap - 90)
        start = a["end"] + (gap - length) / 2
        typical = age.liu("ww", "1")
        if typical and typical < (gap - length) / 2:  # not later than the usual awake time for the age after a sleep
            start = a["end"] + max(typical, 60)
        start = (start - begin) % DAY + begin
        blocks.append({"start": start, "end": start + length, "kind": "nap", "label": "", "basis": "own",
                       "change": f"New in this plan. The logs show about {dur(gap)} with no sleep here. Offer a sleep."})
        blocks.sort(key=lambda x: x["start"])
        for i, x in enumerate(blocks, 1):
            x["label"] = f"Sleep {i}"
        return round(length)
    night, naps = blocks[-1], blocks[:-1]
    earlier = 0 if hold_bedtime else min(BED_STEP, step)  # sleep training runs: bedtime is not for the plan
    if naps and night["start"] - earlier < naps[-1]["end"] + 60:
        earlier = 0
    added = earlier
    if earlier:
        night["change"] = f"{earlier} minutes earlier than {name}'s usual {clock(night['start'])}"
        night["usual"] = night["start"]
        night["start"] -= earlier
    rest = step - earlier
    for b in naps:
        more = min(NAP_STEP, round(rest / len(naps) / 5) * 5)
        nxt = min(x["start"] for x in blocks if x["start"] > b["start"])
        if more >= 10 and b["end"] + more <= nxt - 60:
            b["change"] = f"{more} minutes longer than {name}'s usual {dur(b['end'] - b['start'])}. Do not wake {name}."
            b["end"] += more
            added += more
    return added


def _feeds(age: Age, feeds: list[int], begin: float, months: float) -> tuple[list[dict], dict | None]:
    """The usual feed times of one 24 hours that starts at `begin`, and the number of feeds in 24 hours."""
    windows: dict[int, list[float]] = {}
    for f in feeds:
        d = int((f - begin) // DAY)
        if -DAYS <= d < 0:  # complete 24 hours only
            windows.setdefault(d, []).append(f - d * DAY)
    counts = [len(v) for v in windows.values()]
    feeds_age = age.pub.get("feeds_24h")
    count = blend(counts, feeds_age and feeds_age["p50"])
    if feeds_age:
        age.cite(feeds_age["cite"])
    times: list[float] = []
    basis = "own"
    if len(counts) >= MIN_ROWS:
        k = mode(counts)
        same = [v for v in windows.values() if len(v) == k]
        if len(same) >= MIN_ROWS:  # the days with the most common number of feeds, by position
            times = [median(v[i] for v in same) for i in range(k)]
        else:  # no usual number: the usual first feed, then the usual time between feeds
            k = round(median(counts))
            first = median(v[0] for v in windows.values())
            times = [first + i * (DAY / k) for i in range(k)]
    elif feeds_age:  # too few logs, a young baby: the typical number for the age, at the same distance
        k, basis = round(count["value"]), count["basis"]
        times = [begin + 30 + i * (DAY / k) for i in range(k)]
    return [{"at": t, "basis": basis, "change": None} for t in times], count


def _gaps(rows: list[dict]) -> list[tuple[float, float]]:
    at = sorted(r["at"] for r in rows)
    return list(zip(at, at[1:] + [at[0] + DAY], strict=True)) if at else []


def _new_feed(at: float) -> dict:
    return {"at": at, "basis": "own", "change": "New in this plan. Feed sooner when your baby shows signs of hunger."}


def _gap(rows: list[dict]) -> dict:
    a, b = max(_gaps(rows), key=lambda g: g[1] - g[0])
    return _new_feed((a + b) / 2)


def _block_row(b: dict, name: str) -> dict:
    usual = "low" in b and clock(b["low"]) != clock(b["high"])
    return {"at": b["start"], "time": clock(b["start"]), "end": clock(b["end"]), "kind": b["kind"], "label": b["label"],
            "part": "night" if b["kind"] == "night" else "day", "basis": b["basis"],
            "earliest": clock(b["low"]) if usual else None, "latest": clock(b["high"]) if usual else None,
            "change": b.get("change"), "note": f"About {dur(b['end'] - b['start'])}"}


def _feed_row(f: dict) -> dict:
    return {"at": f["at"], "time": clock(f["at"]), "end": None, "kind": "feed", "label": "Feed", "part": f["part"],
            "basis": f["basis"], "earliest": None, "latest": None, "change": f["change"], "note": None}


def _fact(facts: list, age: Age, key: str, label: str, v: dict | None, field: str | None, fmt, count: bool = False,
          sub: str | None = None, flag: bool = True) -> None:
    """One number of the child, with the child's own usual range and the range that is common for the age."""
    if v is None:
        return
    c = age.common(field, sub) if field else None
    if c:
        age.cite(c[2])
    usual = None
    if "low" in v and fmt(v["low"]) != fmt(v["high"]):
        usual = f"{fmt(v['low'])} to {fmt(v['high'])}"
    value = v["value"]
    facts.append({"key": key, "label": label, "basis": v["basis"], "samples": v["samples"],
                  "value": fmt(round(value) if count and v["basis"] == "own" else value), "usual": usual,
                  "common": f"{fmt(c[0])} to {fmt(c[1])}" if c else None,
                  "outside": bool(flag and c and v["basis"] == "own" and not c[0] <= value <= c[1])})


def _finish(age: Age, months: float, notes: list[dict], out: dict) -> dict:
    """The rules for the age, and a number for each source that the plan used."""
    bands = table()["sleep_bands"]
    b = next(x for x in bands["bands"] if x["min_months"] <= months and (x["max_months"] is None or months < x["max_months"]))
    notes.append({"text": f"Recommended sleep in 24 hours for this age: {b['rec_low']} to {b['rec_high']} hours, naps "
                          f"included. {b['ok_low']} to {b['ok_high']} hours can be right for some children.",
                  "cites": [bands["cite"]]})
    notes += [{"text": x["text"], "cites": list(x["cites"])} for x in age.pub["notes"]]
    both = out["nudges"] + notes
    for x in both:
        for key in x["cites"]:
            age.cite(key)
    src = table()["sources"]
    sources = [{"n": i + 1, "kind": "link", **{a: b for a, b in src[key].items() if b}} for i, key in enumerate(age.used)]
    for x in both:
        x["cites"] = [age.used.index(key) + 1 for key in x["cites"]]
        if c := x.pop("citation", None):
            n = next((y["n"] for y in sources if y.get("url") == c["url"]), None)
            if n is None:
                n = len(sources) + 1
                sources.append({"n": n, "kind": "link", **c})
            x["cites"] = [n]
    return {"age_band": age.pub["label"], "days": DAYS, **out, "notes": notes, "sources": sources}


def _naps(k: int) -> str:
    return "no nap" if k == 0 else "1 nap" if k == 1 else f"{k} naps"
