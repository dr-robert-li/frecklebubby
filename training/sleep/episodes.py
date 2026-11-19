"""Step 1: sleep episodes and sleep-days from the Liu et al. (2019) 10-minute array.

Usage: python episodes.py DATA.mat OUT_DIR

Input: MATLAB v5 file, variable `data`, shape (day of age, 144 bins, infant). Values 0..1 are the fraction of the
10-minute bin asleep (the data has 1-minute steps: 0.0, 0.1, ... 1.0). NaN means the day is missing.
Output (OUT_DIR, outside version control): `episodes.pkl` (one row per sleep episode), `days.pkl` (one row per
complete sleep-day), `events.pkl` (one row per scorable wake-to-sleep transition) and `extract_stats.json`.

Rules (see README):
- A run of consecutive observed days is one segment. Episodes never join across a missing day.
- Partial bin: round(10 * fraction) minutes asleep. They go at the side of the bin next to the more-asleep
  neighbour; with equal neighbours they go in the middle.
- Wake gaps of MERGE_GAP minutes or less are merged (one logged sleep that was split). Episodes under MIN_SLEEP
  minutes after the merge are dropped.
- An episode that touches the start or the end of a segment is censored (its true start or end is unknown).
- Night: for each night D (D 19:00 to D+1 07:00) the anchor is the episode with the largest overlap with that window
  (at least 60 min). Episodes that start between D 18:00 and D+1 08:00 and are at most NIGHT_GAP minutes of wake
  away from the cluster join it (night wakings). NIGHT_GAP comes from the data: the 90th percentile of wake gaps
  between episodes that both lie in the core night 23:00-05:00 (see `night_gap`).
- Sleep-day D = morning wake (end of night D-1) to bedtime (start of night D). Episodes between them are naps.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

MERGE_GAP = 10
MIN_SLEEP = 5
DAY = 1440


def load(path: str) -> np.ndarray:
    """(days, 144, infants) float array. Parse only; the file is untrusted input."""
    d = sio.loadmat(path, variable_names=["data"])["data"]
    if d.ndim != 3 or d.shape[1] != 144:
        raise ValueError(f"unexpected shape {d.shape}")
    return np.asarray(d, dtype=np.float64)


def segments(observed: np.ndarray) -> list[tuple[int, int]]:
    """[(first_day, n_days)] for runs of True."""
    out, start = [], None
    for i, ok in enumerate(list(observed) + [False]):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            out.append((start, i - start))
            start = None
    return out


def to_minutes(bins: np.ndarray) -> np.ndarray:
    """Concatenated 10-minute fractions -> boolean asleep per minute (partial-bin rule above)."""
    m = np.rint(np.clip(bins, 0, 1) * 10).astype(int)
    left = np.r_[0.0, bins[:-1]]
    right = np.r_[bins[1:], 0.0]
    j = np.arange(10)[None, :]
    mm = m[:, None]
    at_start = j < mm
    at_end = j >= 10 - mm
    c0 = ((10 - m) // 2)[:, None]
    middle = (j >= c0) & (j < c0 + mm)
    pick = np.where((left > right)[:, None], at_start, np.where((right > left)[:, None], at_end, middle))
    return pick.reshape(-1)


def runs(asleep: np.ndarray) -> np.ndarray:
    """(start, end) minute pairs of True runs, end exclusive."""
    x = np.r_[0, asleep.astype(np.int8), 0]
    d = np.diff(x)
    return np.c_[np.flatnonzero(d == 1), np.flatnonzero(d == -1)]


def merge(ep: np.ndarray, gap: int = MERGE_GAP, min_sleep: int = MIN_SLEEP) -> np.ndarray:
    if len(ep) == 0:
        return ep
    out = [list(ep[0])]
    for s, e in ep[1:]:
        if s - out[-1][1] <= gap:
            out[-1][1] = e
        else:
            out.append([s, e])
    out = np.array(out, dtype=int)
    return out[(out[:, 1] - out[:, 0]) >= min_sleep]


def segment_episodes(rows: np.ndarray, first_day: int) -> pd.DataFrame:
    """Episodes of one segment, absolute minutes from the birth day 00:00."""
    ep = merge(runs(to_minutes(rows.reshape(-1))))
    total = rows.shape[0] * DAY
    df = pd.DataFrame(ep + first_day * DAY, columns=["start", "end"])
    df["cens_start"] = ep[:, 0] == 0 if len(ep) else []
    df["cens_end"] = ep[:, 1] == total if len(ep) else []
    df["seg_start"], df["seg_end"] = first_day * DAY, first_day * DAY + total
    return df


def night_clusters(ep: pd.DataFrame, night_gap: int) -> dict[int, list[int]]:
    """Night D -> episode row positions (in time order) for nights fully inside the segment."""
    s, e = ep["start"].to_numpy(), ep["end"].to_numpy()
    if len(s) == 0:
        return {}
    seg0, seg1 = int(ep["seg_start"].iloc[0]), int(ep["seg_end"].iloc[0])
    out = {}
    for d in range(seg0 // DAY, seg1 // DAY):
        w0, w1 = d * DAY + 19 * 60, (d + 1) * DAY + 7 * 60
        if w0 < seg0 or w1 > seg1:
            continue
        ov = np.clip(np.minimum(e, w1) - np.maximum(s, w0), 0, None)
        a = int(np.argmax(ov))
        if ov[a] < 60:
            continue
        lo_t, hi_t = d * DAY + 18 * 60, (d + 1) * DAY + 8 * 60
        i = j = a
        while i > 0 and s[i] - e[i - 1] <= night_gap and s[i - 1] >= lo_t:
            i -= 1
        while j + 1 < len(s) and s[j + 1] - e[j] <= night_gap and s[j + 1] < hi_t:
            j += 1
        if ep["cens_start"].iloc[i] or ep["cens_end"].iloc[j]:
            continue
        out[d] = list(range(i, j + 1))
    return out


def night_gap(all_eps: list[pd.DataFrame]) -> int:
    """90th percentile of wake gaps between episodes that both lie within 23:00-05:00, rounded to 10 min."""
    gaps = []
    for ep in all_eps:
        s, e = ep["start"].to_numpy(), ep["end"].to_numpy()
        if len(s) < 2:
            continue
        g = s[1:] - e[:-1]
        a_end = e[:-1] % DAY
        b_start = s[1:] % DAY
        core = lambda t: (t >= 23 * 60) | (t < 5 * 60)  # noqa: E731
        same_night = g < 6 * 60
        gaps.append(g[core(a_end) & core(b_start) & same_night])
    g = np.concatenate(gaps)
    return int(np.clip(round(np.percentile(g, 90) / 10) * 10, 30, 180))


def sleep_days(ep: pd.DataFrame, nights: dict[int, list[int]], infant: int) -> tuple[list[dict], list[dict]]:
    """Complete sleep-days and their wake-to-sleep events."""
    days, events = [], []
    s, e = ep["start"].to_numpy(), ep["end"].to_numpy()
    for d, cur in nights.items():
        prev = nights.get(d - 1)
        if prev is None:
            continue
        wake, bed = int(e[prev[-1]]), int(s[cur[0]])
        naps = list(range(prev[-1] + 1, cur[0]))
        if bed <= wake:
            continue
        nap_s, nap_e = s[naps].astype(int), e[naps].astype(int)
        cur_dur = (e[cur] - s[cur]).astype(int)
        base = d * DAY
        day = {"infant": infant, "day": d, "wake": wake - base, "bedtime": bed - base, "naps": len(naps),
               "day_sleep": int((nap_e - nap_s).sum()), "night_sleep": int(cur_dur.sum()),
               "night_span": int(e[cur[-1]] - s[cur[0]]), "longest_night": int(cur_dur.max()),
               "night_wakings": len(cur) - 1,
               "nap_starts": (nap_s - base).tolist(), "nap_ends": (nap_e - base).tolist()}
        day["total_24h"] = day["day_sleep"] + int((e[prev] - s[prev]).sum())  # last night + this day
        days.append(day)
        ends = [wake] + nap_e.tolist()
        starts = nap_s.tolist() + [bed]
        for k, (w, st) in enumerate(zip(ends, starts, strict=True)):
            kind = "bedtime" if k == len(naps) else "nap"
            dur = int(nap_e[k] - nap_s[k]) if kind == "nap" else int(e[cur[-1]] - s[cur[0]])
            events.append({"infant": infant, "day": d, "kind": kind, "position": k + 1 if kind == "nap" else 0,
                           "naps_before": k, "wake_at": w - base, "start_at": st - base, "ww": st - w,
                           "duration": dur})
    return days, events


def extract(data: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    eps = []
    for n in range(data.shape[2]):
        obs = ~np.isnan(data[:, 0, n])
        for first, length in segments(obs):
            df = segment_episodes(data[first:first + length, :, n], first)
            df["infant"], df["seg"] = n, first
            eps.append(df)
    gap = night_gap(eps)
    all_days, all_events, n_trans = [], [], 0
    for df in eps:
        nights = night_clusters(df, gap)
        df["night"] = -1
        for d, idx in nights.items():
            df.loc[idx, "night"] = d
        n_trans += max(len(df) - 1, 0)
        days, events = sleep_days(df, nights, int(df["infant"].iloc[0]) if len(df) else -1)
        all_days += days
        all_events += events
    ep = pd.concat(eps, ignore_index=True)
    days, events = pd.DataFrame(all_days), pd.DataFrame(all_events)
    in_night = int((ep["night"] >= 0).sum() - ep[ep["night"] >= 0].groupby(["infant", "seg", "night"]).ngroups)
    stats = {"infants": int(ep["infant"].nunique()), "observed_days": int((~np.isnan(data[:, 0, :])).sum()),
             "segments": len(eps), "episodes": len(ep), "censored_episodes": int((ep.cens_start | ep.cens_end).sum()),
             "night_gap_minutes": gap, "within_segment_transitions": n_trans,
             "night_waking_transitions": in_night, "complete_sleep_days": len(days),
             "scorable_events": len(events), "scorable_naps": int((events.kind == "nap").sum()),
             "scorable_bedtimes": int((events.kind == "bedtime").sum())}
    stats["dropped_transitions"] = stats["within_segment_transitions"] - in_night - stats["scorable_events"]
    return ep, days, events, stats


def main(mat: str, out: str) -> None:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ep, days, events, stats = extract(load(mat))
    ep.to_pickle(out_dir / "episodes.pkl")
    days.to_pickle(out_dir / "days.pkl")
    events.to_pickle(out_dir / "events.pkl")
    (out_dir / "extract_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:3])
