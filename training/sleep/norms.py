"""Step 2: descriptive norms by age, nap-count stage statistics and the nap transition ages.

Usage: python norms.py WORK_DIR OUT_JSON FIG_DIR

WORK_DIR holds days.pkl and events.pkl from episodes.py. OUT_JSON gets the aggregate norms (no per-infant rows).
Each infant gives one value per age band: the median of its days in that band (at least MIN_DAYS days). The
percentiles are across infants, so infants with many logged days do not dominate.
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

MIN_DAYS = 3
Q = [10, 25, 50, 75, 90]
MONTH = 30.4375
LIU = {"title": "Time-Series Analysis via Low-Rank Matrix Factorization Applied to Infant-Sleep Data "
                "(Liu S, et al. NeurIPS 2019 Machine Learning for Health workshop)",
       "publisher": "arXiv", "url": "https://arxiv.org/abs/1904.04780", "year": 2019}


def bands() -> list[tuple[int, int]]:
    """Weekly to 26 weeks, fortnightly to 12 months, then by month to 24 months. [min_day, max_day)."""
    out = [(7 * i, 7 * i + 7) for i in range(26)]
    out += [(182 + 14 * i, 182 + 14 * i + 14) for i in range(13)]
    out[-1] = (out[-1][0], 365)
    out += [(round(m * MONTH), round((m + 1) * MONTH)) for m in range(12, 24)]
    out[-1] = (out[-1][0], 730)
    return out


def band_index(day: pd.Series | np.ndarray) -> np.ndarray:
    edges = np.array([b[0] for b in bands()] + [730])
    return np.searchsorted(edges, np.asarray(day), side="right") - 1


def _pct(per_infant: pd.Series) -> list[int] | None:
    v = per_infant.dropna()
    return [int(round(x)) for x in np.percentile(v, Q)] if len(v) >= 10 else None


def _per_infant(df: pd.DataFrame, col: str) -> pd.DataFrame:
    g = df.groupby(["band", "infant"])[col]
    m = g.median()
    return m[g.size() >= MIN_DAYS]


def table(days: pd.DataFrame, events: pd.DataFrame, infants=None) -> list[dict]:
    if infants is not None:
        days, events = days[days.infant.isin(infants)], events[events.infant.isin(infants)]
    days = days.assign(band=band_index(days.day))
    events = events.assign(band=band_index(events.day))
    cols = {c: _per_infant(days, c) for c in ("total_24h", "night_sleep", "day_sleep", "naps", "bedtime", "wake",
                                              "longest_night", "night_wakings", "night_span")}
    ev = {}
    for pos in (1, 2, 3, 4):
        sel = events[(events.kind == "nap") & ((events.position == pos) if pos < 4 else (events.position >= 4))]
        ev[str(pos)] = (_per_infant(sel, "ww"), _per_infant(sel, "duration"))
    bed = events[events.kind == "bedtime"]
    ev["bedtime"] = (_per_infant(bed, "ww"), None)
    # Share of days on 0, 1, 2, 3, 4+ naps: mean over infants of each infant's share (equal weight per infant).
    capped = days.assign(nc=days.naps.clip(upper=4))
    share = (capped.groupby(["band", "infant"]).nc.value_counts(normalize=True).unstack(fill_value=0)
             [capped.groupby(["band", "infant"]).size() >= MIN_DAYS])
    out = []
    for b, (lo, hi) in enumerate(bands()):
        n = int(cols["total_24h"].loc[b].size) if b in cols["total_24h"].index.get_level_values(0) else 0
        row = {"min_days": lo, "max_days": hi, "n_infants": n}
        for c, s in cols.items():
            row[c] = _pct(s.loc[b]) if n else None
        row["ww"] = {k: (_pct(w.loc[b]) if b in w.index.get_level_values(0) else None) for k, (w, _) in ev.items()}
        row["nap_minutes"] = {k: (_pct(d.loc[b]) if b in d.index.get_level_values(0) else None)
                              for k, (_, d) in ev.items() if d is not None}
        row["naps_share"] = ({str(k): round(float(v), 3) for k, v in share.loc[b].mean().items()}
                             if b in share.index.get_level_values(0) else None)
        out.append(row)
    return out


def transitions(days: pd.DataFrame, frm: int, window: int = 14, min_obs: int = 7) -> dict:
    """Age (days) at which an infant moves from `frm` naps to fewer. Share of days with fewer than `frm` naps in a
    trailing 14-day window (at least 7 observed days): onset = first day the share reaches 20 %, the transition age
    = first day it reaches 50 %, settled = first day it reaches 80 %. Only infants seen below 20 % first (on `frm`
    or more naps) and then past 80 % count."""
    ages, durs = [], []
    for _, d in days.groupby("infant"):
        s = pd.Series((d.naps < frm).astype(float).to_numpy(), index=d.day.to_numpy())
        s = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1))
        sh = s.rolling(window, min_periods=min_obs).mean().dropna()
        first_low = sh[sh < 0.2]
        if first_low.empty:
            continue
        done = sh[(sh.index > first_low.index[0]) & (sh >= 0.8)]
        if done.empty:
            continue
        # The last time the infant was still mostly on `frm` naps before it settled.
        last_low = sh[(sh.index < done.index[0]) & (sh < 0.2)].index[-1]
        rest = sh[sh.index > last_low]
        onset = rest[rest >= 0.2].index[0]
        mid = rest[rest >= 0.5]
        ages.append(mid.index[0])
        durs.append(done.index[0] - onset)
    if len(ages) < 10:
        return {"n_infants": len(ages)}
    return {"n_infants": len(ages), "age_days": [int(x) for x in np.percentile(ages, Q)],
            "duration_days": [int(x) for x in np.percentile(durs, Q)]}


def figures(rows: list[dict], fig_dir: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    mid = np.array([(r["min_days"] + r["max_days"]) / 2 / MONTH for r in rows])
    names = []

    def band(ax, key, sub=None, scale=1 / 60, label=None, color="C0"):
        vals = [(r[key] if sub is None else (r[key] or {}).get(sub)) for r in rows]
        ok = [v is not None for v in vals]
        v = np.array([x for x in vals if x is not None]) * scale
        x = mid[ok]
        ax.fill_between(x, v[:, 0], v[:, 4], alpha=0.15, color=color)
        ax.fill_between(x, v[:, 1], v[:, 3], alpha=0.3, color=color)
        ax.plot(x, v[:, 2], color=color, label=label or key)

    fig, ax = plt.subplots(figsize=(8, 5))
    band(ax, "total_24h", label="total per 24 h (P10-P90, P25-P75, P50)", color="C0")
    band(ax, "night_sleep", label="night sleep", color="C1")
    band(ax, "day_sleep", label="day sleep", color="C2")
    for lo, hi, a, b in ((0, 4, 14, 17), (4, 12, 12, 15), (4, 12, 12, 16), (12, 24, 11, 14)):
        ax.plot([lo, hi], [a, a], "k--", lw=0.8)
        ax.plot([lo, hi], [b, b], "k--", lw=0.8)
    ax.set(xlabel="Age (months)", ylabel="Hours", title="Logged sleep by age (dashed: AASM 2016 / NSF 2015 ranges)")
    ax.legend(fontsize=8)
    fig.savefig(fig_dir / "norms_sleep_hours.png", dpi=120)
    names.append("norms_sleep_hours.png")

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, k in enumerate(("1", "2", "3", "4", "bedtime")):
        vals = [(r["ww"] or {}).get(k) for r in rows]
        ok = [v is not None for v in vals]
        ax.plot(mid[ok], [v[2] / 60 for v in vals if v], color=f"C{i}", label=f"before nap {k}" if k != "bedtime"
                else "before bedtime")
    ax.set(xlabel="Age (months)", ylabel="Hours (median of infant medians)", title="Wake window by position")
    ax.legend(fontsize=8)
    fig.savefig(fig_dir / "norms_wake_windows.png", dpi=120)
    names.append("norms_wake_windows.png")

    fig, ax = plt.subplots(figsize=(8, 5))
    sh = np.array([[(r["naps_share"] or {}).get(str(k), np.nan) for k in range(5)] for r in rows])
    ax.stackplot(mid, np.nan_to_num(sh.T), labels=["0 naps", "1 nap", "2 naps", "3 naps", "4+ naps"])
    ax.set(xlabel="Age (months)", ylabel="Share of days", title="Logged naps per day by age", ylim=(0, 1))
    ax.legend(fontsize=8, loc="upper left")
    fig.savefig(fig_dir / "norms_nap_count.png", dpi=120)
    names.append("norms_nap_count.png")

    fig, ax = plt.subplots(figsize=(8, 5))
    band(ax, "bedtime", label="bedtime", color="C3")
    band(ax, "wake", label="morning wake", color="C4")
    ax.set(xlabel="Age (months)", ylabel="Clock hour", title="Bedtime and morning wake (local clock)")
    ax.legend(fontsize=8)
    fig.savefig(fig_dir / "norms_clock.png", dpi=120)
    names.append("norms_clock.png")
    plt.close("all")
    return names


def build(days: pd.DataFrame, events: pd.DataFrame, infants=None) -> dict:
    d = days if infants is None else days[days.infant.isin(infants)]
    return {
        "about": ("Aggregate sleep norms by age from the Liu et al. (2019) infant-sleep dataset (Baby Connect app users,"
                  " logged by parents). Minutes, except naps (count) and bedtime/wake (minutes after local midnight of"
                  " the day; above 1440 = after midnight). Percentiles P10, P25, P50, P75, P90 across infants. No"
                  " per-infant data."),
        "source": LIU, "generated": date.today().isoformat(), "infants": int(d.infant.nunique()),
        "percentiles": Q, "bands": table(days, events, infants),
        "transitions": {f"{k}to{k - 1}": transitions(d, k) for k in (4, 3, 2)},
    }


def main(work: str, out_json: str, fig_dir: str) -> None:
    w = Path(work)
    days, events = pd.read_pickle(w / "days.pkl"), pd.read_pickle(w / "events.pkl")
    norms = build(days, events)
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(norms, indent=1))
    print(figures(norms["bands"], Path(fig_dir)))
    print(json.dumps(norms["transitions"]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
