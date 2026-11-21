"""Replay the day and night plan (services/regime.py) on the research data of Liu et al. (2019).

For each infant and each age (every 14 days): the plan is calculated from the days before the age, exactly as the
app does it, and compared with what the infant did in the 7 days after it.

1. Rule checks (all infants): does the plan break a simple rule? Blocks that overlap, a block of a wrong length,
   an error. And: how often does the plan take a step, and how often does it say "rough guide"?
2. Fit (test infants only): how far is the start point of the plan (no steps) from the next 7 days? Compared with
   two simple plans: "the same as yesterday" and "typical for the age".
3. Settings (train infants pick, test infants report): the days of logs that the plan reads (DAYS) and the days
   from which it uses only the infant's own values (MIN_OWN).

The data has sleep only, no feeds. The norms file of the app was made from all infants of this data, so the plan
"typical for the age" has seen the test infants; the plans from an infant's own days almost do not use it.

Run:  uv run python replay_plan.py WORK_DIR OUT.json [PROCESSES]
"""

import json
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd
from predict import split

from frecklebubby.services import regime
from frecklebubby.services.sleep import DAY, nights, sleep_days

AGES = range(21, 716, 14)
HIST, FUT = 23, 8  # days of history that each setting can read; days after the age for the comparison
GRID = [(d, m) for d in (7, 10, 14, 21) for m in (3, 5, 7)]
BANDS = [(0, 3), (3, 6), (6, 12), (12, 18), (18, 24)]
GAP = 70
NOW = 600  # the plan is made at 10:00 of the day


def mins(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:])


def blocks(plan: dict) -> list[tuple[int, int, str]]:
    """Sleep blocks of a plan as (start, end, kind): minutes of the clock of the first day, in the order of the plan
    (a block after midnight is above 1440)."""
    out, last = [], None
    for r in plan["schedule"]:
        if r["kind"] == "feed":
            continue
        a, b = mins(r["time"]), mins(r["end"])
        if last is not None and a < last:
            a += DAY
        b += DAY * ((a - b) // DAY + 1) if b <= a else 0
        out.append((a, b, r["kind"]))
        last = a
    return out


def rule_faults(plan: dict) -> list[str]:
    bl = blocks(plan)
    faults = []
    for (a, b, _), nxt in zip(bl, bl[1:] + [None], strict=True):
        if b - a < 5 or b - a > 16 * 60:  # a nap of 10 or 15 minutes is real in this data
            faults.append("block length")
        if nxt and nxt[0] < b:
            faults.append("overlap")
    if bl and bl[-1][1] - bl[0][0] > DAY + 5:
        faults.append("more than 24 hours")
    if plan["mode"] == "clock" and plan["confidence"] == "normal" and plan["basis"] != "age":
        night = [b - a for a, b, k in bl if k == "night"]
        if len(night) != 1 or not 6 * 60 <= night[0] <= 15 * 60:
            faults.append("night block")
    total = sum(b - a for a, b, _ in bl)
    if not 4 * 60 <= total <= 22 * 60:
        faults.append("total sleep")
    return faults


def actual(eps: list[list[int]]) -> dict | None:
    """What the infant did in the days after the age: medians over the complete sleep-days."""
    days = [d for d in sleep_days(eps, nights(eps, GAP)) if 0 <= d["day"] < FUT - 1]
    if len(days) < 4:
        return None
    k = Counter(d["naps"] for d in days).most_common(1)[0][0]
    same = [d for d in days if d["naps"] == k]
    return {"bed": median(d["bedtime"] for d in days), "wake": median(d["ends"][0] - d["day"] * DAY for d in days),
            "naps": k, "nap_starts": [median(d["starts"][i] - d["day"] * DAY for d in same) for i in range(k)],
            "total": median(sum(d["durations"]) for d in days)}


def asleep(eps: list[list[int]], days: range) -> np.ndarray:
    """Share of the days on which each 10 minutes of the clock is asleep."""
    grid = np.zeros((len(days), 144))
    for i, d in enumerate(days):
        for a, b in eps:
            lo, hi = max(a, d * DAY), min(b, (d + 1) * DAY)
            if hi > lo:
                grid[i, (lo - d * DAY) // 10:-(-(hi - d * DAY) // 10)] = 1
    return grid.mean(axis=0)


def plan_grid(bl: list[tuple[int, int, str]]) -> np.ndarray:
    g = np.zeros(144)
    for a, b, _ in bl:
        for m in range(a, b, 10):
            g[(m % DAY) // 10] = 1
    return g


def compare(plan: dict, act: dict | None, fut_share: np.ndarray) -> dict:
    """The distance from a plan to the next days. Clock values in minutes; cover = the share of the planned sleep
    minutes in which the infant was really asleep (weighted by days), and the same for the real sleep."""
    bl = blocks(plan)
    out = {}
    if bl:
        g = plan_grid(bl)
        out["precision"] = float((g * fut_share).sum() / max(g.sum(), 1))
        out["recall"] = float((g * fut_share).sum() / max(fut_share.sum(), 1e-9))
    if act and plan["mode"] == "clock":
        night = next(((a, b) for a, b, k in bl if k == "night"), None)
        naps = [(a, b) for a, b, k in bl if k == "nap"]
        if night:
            bed = night[0] % DAY
            bed += DAY if bed < 12 * 60 else 0
            out["bed_err"] = abs(bed - act["bed"])
            out["wake_err"] = abs(night[1] % DAY - act["wake"])
        out["naps_same"] = float(len(naps) == act["naps"])
        if len(naps) == act["naps"] and naps:
            out["nap_err"] = float(np.mean([abs(a % DAY - s) for (a, _), s in zip(naps, act["nap_starts"], strict=True)]))
        out["total_err"] = abs(sum(b - a for a, b, _ in bl) - act["total"])
    return out


def yesterday(eps: list[list[int]]) -> dict | None:
    """A simple plan: the same as the last complete sleep-day."""
    days = [d for d in sleep_days(eps, nights(eps, GAP)) if d["day"] < 0]
    if not days:
        return None
    d = days[-1]
    rows = [{"time": regime.clock(s - d["day"] * DAY), "end": regime.clock(s - d["day"] * DAY + n), "kind": "nap"}
            for s, n in zip(d["starts"][:-1], d["durations"][:-1], strict=True)]
    rows.append({"time": regime.clock(d["bedtime"]), "end": regime.clock(d["bedtime"] + d["durations"][-1]), "kind": "night"})
    return {"schedule": rows, "mode": "clock", "confidence": "normal", "basis": "own"}


def one_infant(args) -> list[dict]:
    infant, ep = args
    out = []
    for t in AGES:
        seg = ep[(ep[:, 2] <= (t - HIST) * DAY) & (ep[:, 3] >= (t + FUT) * DAY)]
        if not len(seg):
            continue
        rel = (seg[:, :2] - t * DAY)
        hist = [[int(a), int(b)] for a, b in rel if b <= NOW and a >= -HIST * DAY]  # the app reads to "now"
        fut = [[int(a), int(b)] for a, b in rel if a >= -DAY and b <= FUT * DAY]
        act = actual(fut)
        share = asleep(fut, range(0, FUT - 1))
        row = {"infant": infant, "age": t}
        try:
            full = regime.calculate("Baby", t, hist, [], NOW)
            row.update(mode=full["mode"], basis=full["basis"], confidence=full["confidence"], faults=rule_faults(full),
                       steps=["long sleep check" if "does not cut" in n["text"] else "nap ends earlier"
                              if "ends the nap" in n["text"] else "more sleep, smallest step"
                              if "can also be right" in n["text"] else "more sleep" for n in full["nudges"]],
                       doubt=next((n["text"].split(": ", 1)[1].split(".")[0][:40] for n in full["notes"][:1]
                                   if "do not show one regular pattern" in n["text"]), None),
                       bad=[(r["time"], r["end"], r["kind"]) for r in full["schedule"] if r["kind"] != "feed"]
                       if rule_faults(full) else None,
                       changed=sum(bool(r["change"]) for r in full["schedule"]))
            base = regime.calculate("Baby", t, hist, [], NOW, steps=False)
            row["plan"] = compare(base, act, share)
            row["age_plan"] = compare(regime.calculate("Baby", t, [], [], NOW), act, share)
            y = yesterday(hist)
            row["yesterday"] = compare(y, act, share) if y else {}
            row["grid"] = {}
            for days, own in GRID:
                regime.DAYS, regime.MIN_OWN = days, own
                row["grid"][f"{days}/{own}"] = compare(regime.calculate("Baby", t, hist, [], NOW, steps=False), act, share)
            regime.DAYS, regime.MIN_OWN = 14, 5
        except Exception as err:  # the calculator must not fail on real data
            row["error"] = f"{type(err).__name__}: {err}"
            regime.DAYS, regime.MIN_OWN = 14, 5
        out.append(row)
    return out


def band(age_days: int) -> str:
    m = age_days / 30.4375
    return next((f"{a}-{b} months" for a, b in BANDS if a <= m < b), "24 months")


def mean_of(rows: list[dict], key: str, field: str) -> float | None:
    v = [r[key][field] for r in rows if field in r.get(key, {})]
    return round(float(np.mean(v)), 3) if v else None


def summary(rows: list[dict], test: set) -> dict:
    out = {"plans": len(rows), "infants": len({r["infant"] for r in rows}),
           "errors": Counter(r["error"] for r in rows if "error" in r)}
    ok = [r for r in rows if "error" not in r]
    by = defaultdict(list)
    for r in ok:
        by[band(r["age"])].append(r)
    out["rules"] = {}
    for b, rs in by.items():
        faults = Counter(f for r in rs for f in set(r["faults"]))
        out["rules"][b] = {
            "plans": len(rs), "mode_rhythm": round(np.mean([r["mode"] == "rhythm" for r in rs]), 3),
            "rough_guide": round(np.mean([r["confidence"] == "low" for r in rs]), 3),
            "with_fault": round(np.mean([bool(r["faults"]) for r in rs]), 4), "faults": dict(faults),
            "with_step": round(np.mean([r["changed"] > 0 for r in rs]), 3),
            "step_more_sleep": round(np.mean(["more sleep" in r["steps"] for r in rs]), 3),
            "step_more_sleep_smallest": round(np.mean(["more sleep, smallest step" in r["steps"] for r in rs]), 3),
            "doubts": dict(Counter(r["doubt"] for r in rs if r["doubt"])),
            "fault_examples": [r["bad"] for r in rs if r["bad"]][:3],
            "step_nap_earlier": round(np.mean(["nap ends earlier" in r["steps"] for r in rs]), 3),
            "long_sleep_check": round(np.mean(["long sleep check" in r["steps"] for r in rs]), 4)}
    fields = ("bed_err", "wake_err", "nap_err", "naps_same", "total_err", "precision", "recall")
    tests = [r for r in ok if r["infant"] in test]
    out["fit_test"] = {}
    for b in list(by) + ["all"]:
        rs = [r for r in tests if b == "all" or band(r["age"]) == b]
        out["fit_test"][b] = {"plans": len(rs), **{k: {f: mean_of(rs, k, f) for f in fields} for k in ("plan", "yesterday", "age_plan")}}
    train = [r for r in ok if r["infant"] not in test]
    out["settings"] = {}
    for key in (f"{d}/{m}" for d, m in GRID):
        out["settings"][key] = {
            "train": {f: mean_of([{"g": r["grid"][key]} for r in train], "g", f) for f in fields},
            "test": {f: mean_of([{"g": r["grid"][key]} for r in tests], "g", f) for f in fields}}
    return out


def main(work: str, out_path: str, procs: int = 16) -> None:
    ep = pd.read_pickle(Path(work) / "episodes.pkl")
    ep = ep[~(ep.cens_start | ep.cens_end)]
    groups = [(int(i), g[["start", "end", "seg_start", "seg_end"]].to_numpy()) for i, g in ep.groupby("infant")]
    _, _, test = split(np.array([i for i, _ in groups]))
    with Pool(procs) as pool:
        rows = [r for part in pool.imap_unordered(one_infant, groups, chunksize=4) for r in part]
    res = summary(rows, set(test))
    res["test_infants"], res["ages_days"] = len(test), [AGES.start, AGES.stop, AGES.step]
    Path(out_path).write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("plans", "infants", "errors", "rules")}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 16)
