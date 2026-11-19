"""Step 4: next-sleep predictor comparison with a split by infant (60 % train, 20 % validation, 20 % test).

Usage: python predict.py WORK_DIR NORMS_JSON OUT_DIR

Task: at the moment the child wakes (end of the night or of a nap, inside a complete sleep-day, see episodes.py),
predict the start of the next sleep and whether it is a nap or bedtime. When a sleep starts, predict its length.
Methods:
  a  the app's method before M7 (services/sleep.py), re-implemented on the episodes (`legacy`)
  b  age norm: train-infant median wake window for the age band and position, and a clock threshold for bedtime
  c  shrinkage: the child's recent wake windows for the same position, blended with (b); bedtime also blends the
     child's usual bedtime clock time. k (prior weight), H (days) and w (clock weight) are tuned on validation.
  d  gradient-boosted quantile models (P10, P50, P90) and a classifier for nap or bedtime.
Everything that is tuned uses validation infants only. Test infants are scored once.
OUT_DIR gets predict_results.json and the `model` block that the app reads from the norms file.
"""

import json
import math
import sys
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from statistics import median

import norms as N
import numpy as np
import pandas as pd

DAY = 1440
HMAX = 14
SPLIT_SEED = 7


def split(infants: np.ndarray) -> tuple[list, list, list]:
    p = np.random.default_rng(SPLIT_SEED).permutation(np.sort(infants))
    a, b = int(0.6 * len(p)), int(0.8 * len(p))
    return sorted(p[:a].tolist()), sorted(p[a:b].tolist()), sorted(p[b:].tolist())


# --- lookups from a norms table -----------------------------------------------------------------------------------

def lookups(rows: list[dict]) -> dict:
    """band -> {key: P50} with gaps filled from the nearest band that has a value."""
    keys = ["1", "2", "3", "4", "bedtime"]

    def fill(get):
        vals = [get(r) for r in rows]
        idx = [i for i, v in enumerate(vals) if v is not None]
        return [vals[min(idx, key=lambda j: abs(j - i))] if idx else None for i in range(len(vals))]

    out = {"ww": {k: fill(lambda r, k=k: (r["ww"] or {}).get(k) and r["ww"][k][2]) for k in keys},
           "dur": {k: fill(lambda r, k=k: (r["nap_minutes"] or {}).get(k) and r["nap_minutes"][k][2]) for k in keys[:4]},
           "bed": fill(lambda r: r["bedtime"] and r["bedtime"][2])}
    out["dur"]["bedtime"] = fill(lambda r: r["night_span"] and r["night_span"][2])
    return out


def key_of(kind: str, position: int) -> str:
    return "bedtime" if kind == "bedtime" else str(min(position, 4))


def thresholds(ev: pd.DataFrame) -> list[list[int]]:
    """band x naps-so-far (0..4+) -> clock minute of the wake after which bedtime is more likely than a nap."""
    out = []
    for b in range(len(N.bands())):
        row = []
        for k in range(5):
            sel = ev[(ev.band == b) & (ev.naps_before.clip(upper=4) == k)]
            if len(sel) < 30:
                row.append(row[-1] if row else 1080)
                continue
            t = np.sort(sel.wake_at.to_numpy())
            bed = sel.sort_values("wake_at").kind.eq("bedtime").to_numpy()
            # errors if the threshold is just before t[i]: naps at or after i, bedtimes before i.
            err = (~bed[::-1]).cumsum()[::-1] + np.r_[0, bed.cumsum()[:-1]]
            row.append(int(t[int(np.argmin(err))]))
        out.append(row)
    return out


# --- features -----------------------------------------------------------------------------------------------------

def infant_features(args, look, H_list):
    """Per event and per history length H: the inputs every method needs. Plain loops; one infant per call."""
    days, ev = args
    days = days.sort_values("day")
    dmap = {int(r.day): r for r in days.itertuples()}
    by_key: dict[str, list] = {}
    for r in ev.itertuples():
        by_key.setdefault(key_of(r.kind, r.position), []).append(r)
    out = []
    for r in ev.itertuples():
        D, b = int(r.day), int(N.band_index([r.day])[0])
        today = dmap[D]
        k = int(r.naps_before)
        prev_dur = (today.total_24h - today.day_sleep) if k == 0 else today.nap_ends[k - 1] - today.nap_starts[k - 1]
        cands = {"nap": key_of("nap", k + 1), "bedtime": "bedtime"}
        for H in H_list:
            f = {"infant": r.infant, "day": D, "band": b, "H": H, "kind": r.kind, "position": r.position,
                 "naps_before": k, "wake_at": r.wake_at, "start_at": r.start_at, "ww": r.ww, "duration": r.duration,
                 "morning_wake": today.wake, "prev_dur": prev_dur, "last_night": today.total_24h - today.day_sleep}
            hist = [dmap[d] for d in range(D - H, D) if d in dmap]
            f["hist_days"] = len(hist)
            f["child_naps"] = median([h.naps for h in hist]) if hist else np.nan
            f["child_bed"] = median([h.bedtime for h in hist]) if hist else np.nan
            for name, key in cands.items():
                same = [x for x in by_key.get(key, []) if D - H <= x.day < D]
                ww = [x.ww for x in same]
                f[f"{name}_n"] = len(ww)
                f[f"{name}_med"] = median(ww) if ww else np.nan
                lr = [math.log(x.ww / look["ww"][key][N.band_index([x.day])[0]]) for x in same if x.ww > 0]
                f[f"{name}_lr"] = median(lr) if lr else np.nan
                dur = [x.duration for x in same]
                f[f"{name}_dur"] = median(dur) if dur else np.nan
                f[f"{name}_norm"] = look["ww"][key][b]
                f[f"{name}_norm_dur"] = look["dur"][key][b]
            out.append(f)
    return out


def features(days, events, infants, look, H_list, procs=16) -> pd.DataFrame:
    d = days[days.infant.isin(infants)]
    e = events[events.infant.isin(infants)]
    groups = [(g, e[e.infant == n]) for n, g in d.groupby("infant")]
    with Pool(procs) as p:
        rows = p.map(partial(infant_features, look=look, H_list=H_list), groups, chunksize=4)
    return pd.DataFrame([x for r in rows for x in r])


# --- methods ------------------------------------------------------------------------------------------------------

def method_b(f: pd.DataFrame, thr) -> pd.DataFrame:
    t = np.array([thr[b][min(k, 4)] for b, k in zip(f.band, f.naps_before, strict=True)])
    bed = f.wake_at.to_numpy() >= t
    ww = np.where(bed, f.bedtime_norm, f.nap_norm)
    dur = np.where(bed, f.bedtime_norm_dur, f.nap_norm_dur)
    return pd.DataFrame({"bed": bed, "pred": f.wake_at + ww, "dur": dur}, index=f.index)


def method_c(f: pd.DataFrame, thr, k0: float, w: float, kind_rule: str, k_dur: float = 3.0) -> pd.DataFrame:
    """Shrinkage in log space: norm * exp(n / (n + k0) * median log(child / norm at that age))."""
    t = np.array([thr[b][min(k, 4)] for b, k in zip(f.band, f.naps_before, strict=True)])
    bed = f.wake_at.to_numpy() >= t
    if kind_rule == "child_naps":
        cn = np.rint(f.child_naps.to_numpy())
        bed = np.where(np.isnan(cn), bed, f.naps_before.to_numpy() >= cn)
    elif kind_rule == "child_naps_or_clock":
        cn = np.rint(f.child_naps.to_numpy())
        bed = np.where(np.isnan(cn), bed, (f.naps_before.to_numpy() >= cn) | (f.wake_at.to_numpy() >= t + 60))

    def blend(name):
        n = f[f"{name}_n"].to_numpy()
        lr = np.nan_to_num(f[f"{name}_lr"].to_numpy())
        return f[f"{name}_norm"].to_numpy() * np.exp(n / (n + k0) * lr) if k0 > 0 else np.where(
            n > 0, f[f"{name}_norm"] * np.exp(lr), f[f"{name}_norm"])

    nap_start = f.wake_at + blend("nap")
    bed_ww = f.wake_at + blend("bedtime")
    cb = f.child_bed.to_numpy()
    hd = f.hist_days.to_numpy()
    bed_start = np.where(np.isnan(cb), bed_ww, (1 - w * hd / (hd + 1)) * bed_ww + w * hd / (hd + 1) * cb)
    bed_start = np.maximum(bed_start, f.wake_at + 15)
    pred = np.where(bed, bed_start, nap_start)

    def dur(name):
        n = f[f"{name}_n"].to_numpy()
        own = f[f"{name}_dur"].to_numpy()
        return np.where(n > 0, (n * np.nan_to_num(own) + k_dur * f[f"{name}_norm_dur"]) / (n + k_dur),
                        f[f"{name}_norm_dur"])

    return pd.DataFrame({"bed": bed, "pred": pred, "dur": np.where(bed, dur("bedtime"), dur("nap"))}, index=f.index)


# --- (a): the app before M7 -------------------------------------------------------------------------------------------

def _is_night(t: int, early: int = 60) -> bool:
    """children.is_night with the default night_start 19:00 and morning_cutoff 07:00 (local minute of day)."""
    t %= DAY
    return t >= 19 * 60 - early or t < 7 * 60


def wake_range(months: float, bands) -> tuple[int, int]:
    row = next((b for b in bands if b["min_months"] <= months and (b["max_months"] is None or months < b["max_months"])),
               bands[-1])
    return row["min_minutes"], row["max_minutes"]


def legacy(sleeps: list[tuple[int, int]], now: int, age_days: int, bands) -> dict | None:
    """services/sleep.predict before M7 on plain minutes. `sleeps` = (start, end) with end <= now, by start."""
    lo, hi = wake_range(age_days / 30.4375, bands)
    sleeps = [x for x in sleeps if x[0] >= now - 8 * DAY and x[1] <= now]
    if not sleeps:
        return None
    last_end = max(e for _, e in sleeps)
    if last_end < now - DAY:
        return None
    samples, position, prev = [], 0, None
    for s, e in sleeps:
        night = _is_night(s)
        if prev is not None and s >= now - 7 * DAY:
            gap = s - prev[0][1]
            if gap > 0 and not (night and prev[1]):
                samples.append((position, gap))
        position = 0 if night else position + 1
        prev = ((s, e), night)
    same = [g for p, g in samples if p == position]
    if len(same) >= 3:
        ww = median(same)
    elif len(samples) >= 3:
        ww = median(g for _, g in samples)
    else:
        ww = (lo + hi) / 2
    ww = round(min(max(ww, lo), hi))
    start = last_end + ww - 15
    if _is_night(last_end, 0) and _is_night(start, 0):
        return None
    return {"start": start, "end": start + 30, "kind": "bedtime" if _is_night(start + 30) else "nap", "ww": ww}


def method_a(f: pd.DataFrame, episodes: pd.DataFrame, bands) -> pd.DataFrame:
    out = []
    eps = {n: g.sort_values("start")[["start", "end"]].to_numpy() for n, g in episodes.groupby("infant")}
    for r in f.itertuples():
        ep = eps[r.infant]
        now = r.day * DAY + r.wake_at
        lo = r.day * DAY - (r.H + 1) * DAY + 18 * 60  # history: from the evening before the first history day
        i0, i1 = np.searchsorted(ep[:, 0], [max(lo, now - 8 * DAY), now], side="left")
        sl = [(int(s), int(e)) for s, e in ep[i0:i1] if e <= now]
        p = legacy(sl, now, r.day, bands)
        out.append((np.nan, np.nan) if p is None else (p["kind"] == "bedtime", p["start"] + 15 - r.day * DAY))
    a = np.array(out, dtype=float)
    return pd.DataFrame({"bed": a[:, 0], "pred": a[:, 1]}, index=f.index)


# --- (d) --------------------------------------------------------------------------------------------------------------

FEATS = ["day", "wake_at", "naps_before", "morning_wake", "prev_dur", "last_night", "hist_days", "child_naps",
         "child_bed", "nap_n", "nap_med", "nap_lr", "nap_norm", "bedtime_n", "bedtime_med", "bedtime_lr",
         "bedtime_norm"]


def fit_d(tr: pd.DataFrame, va: pd.DataFrame):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    kw = {"max_iter": 400, "learning_rate": 0.08, "max_leaf_nodes": 31, "early_stopping": True,
          "validation_fraction": 0.1, "random_state": 0}
    clf = HistGradientBoostingClassifier(**kw).fit(tr[FEATS], tr.kind == "bedtime")
    regs = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, **kw).fit(tr[FEATS], tr.ww)
            for q in (0.1, 0.5, 0.9)}
    return clf, regs


def method_d(f, clf, regs) -> pd.DataFrame:
    X = f[FEATS]
    return pd.DataFrame({"bed": clf.predict(X), "pred": f.wake_at + regs[0.5].predict(X),
                         "lo": f.wake_at + regs[0.1].predict(X), "hi": f.wake_at + regs[0.9].predict(X)}, index=f.index)


# --- metrics ----------------------------------------------------------------------------------------------------------

def interval(p: pd.DataFrame, f: pd.DataFrame, q: dict | None) -> pd.DataFrame:
    """Add lo/hi: 80 % interval from validation quantiles of log(actual / predicted wake window)."""
    if "lo" in p:
        return p
    ww = (p.pred - f.wake_at).clip(lower=5)
    if q is None:  # the app's fixed +-15 min window
        return p.assign(lo=p.pred - 15, hi=p.pred + 15)
    has = np.where(f.hist_days > 0, "h", "0")
    kind = np.where(p.bed.astype(bool), "bedtime", "nap")
    lo = np.array([q[f"{k}_{h}"][0] for k, h in zip(kind, has, strict=True)])
    hi = np.array([q[f"{k}_{h}"][1] for k, h in zip(kind, has, strict=True)])
    return p.assign(lo=f.wake_at + ww * np.exp(lo), hi=f.wake_at + ww * np.exp(hi))


def residual_q(p: pd.DataFrame, f: pd.DataFrame) -> dict:
    ww = (p.pred - f.wake_at).clip(lower=5)
    lr = np.log(f.ww.clip(lower=5) / ww)
    kind = np.where(p.bed.astype(bool), "bedtime", "nap")
    out = {}
    for k in ("nap", "bedtime"):
        for h, m in (("0", f.hist_days == 0), ("h", f.hist_days > 0)):
            v = lr[(kind == k) & m]
            if len(v) == 0:
                continue
            out[f"{k}_{h}"] = [round(float(np.percentile(v, 10)), 3), round(float(np.percentile(v, 90)), 3)]
    return out


def score(p: pd.DataFrame, f: pd.DataFrame) -> dict:
    ok = p.pred.notna()
    err = (p.pred - f.start_at)[ok]
    a = err.abs()
    out = {"n": int(ok.sum()), "coverage_of_events": round(float(ok.mean()), 3),
           "median_ae": round(float(a.median()), 1), "mae": round(float(a.mean()), 1),
           "within_15": round(float((a <= 15).mean()), 3), "within_30": round(float((a <= 30).mean()), 3),
           "kind_accuracy": round(float((p.bed[ok].astype(bool) == (f.kind[ok] == "bedtime")).mean()), 3)}
    if "lo" in p:
        inside = (f.start_at[ok] >= p.lo[ok]) & (f.start_at[ok] <= p.hi[ok])
        out["interval_coverage"] = round(float(inside.mean()), 3)
        out["interval_width"] = round(float((p.hi - p.lo)[ok].median()), 1)
    if "dur" in p:
        out["duration_mae_nap"] = round(float((p.dur - f.duration)[ok & (f.kind == "nap")].abs().mean()), 1)
        out["duration_mae_night"] = round(float((p.dur - f.duration)[ok & (f.kind == "bedtime")].abs().mean()), 1)
    return out


AGE_GROUPS = [(0, 91, "0-3 mo"), (91, 182, "3-6 mo"), (182, 365, "6-12 mo"), (365, 730, "12-24 mo")]


def main(work: str, norms_json: str, out: str) -> None:
    w, out_dir = Path(work), Path(out)
    days, events = pd.read_pickle(w / "days.pkl"), pd.read_pickle(w / "events.pkl")
    episodes = pd.read_pickle(w / "episodes.pkl")
    train, val, test = split(days.infant.unique())
    rows = N.table(days, events, train)
    look = lookups(rows)
    tev = events[events.infant.isin(train)].assign(band=lambda x: N.band_index(x.day))
    thr = thresholds(tev)
    bands = json.loads((Path(__file__).parents[2] / "src/frecklebubby/data/wake_windows.json").read_text())[
        "wake_windows"]["bands"]
    res = {"split": {"train": len(train), "validation": len(val), "test": len(test)}}

    # Validation: tune c.
    fv = features(days, events, val, look, [1, 3, 5, 7, 10, 14])
    grid = []
    for H in (3, 5, 7, 10, 14):
        f = fv[fv.H == H]
        for rule in ("clock", "child_naps", "child_naps_or_clock"):
            for k0 in (0, 1, 2, 4, 8):
                for wt in (0, 0.25, 0.5, 0.75):
                    s = score(method_c(f, thr, k0, wt, rule), f)
                    grid.append({"H": H, "rule": rule, "k0": k0, "w": wt, **s})
    g = pd.DataFrame(grid)
    best = g.sort_values("mae").iloc[0]
    res["validation_best_c"] = best.to_dict()
    res["validation_top"] = g.sort_values("mae").head(8).to_dict("records")
    print("validation best c:", best.to_dict())
    H, rule, k0, wt = int(best.H), best.rule, float(best.k0), float(best.w)
    k_dur = min((1, 2, 3, 5, 8), key=lambda k: score(method_c(fv[fv.H == H], thr, k0, wt, rule, k), fv[fv.H == H])[
        "duration_mae_nap"])
    fvh = fv[fv.H == H]
    q_c = residual_q(method_c(fvh, thr, k0, wt, rule, k_dur), fvh)
    fv0 = features(days, events, val, look, [0])
    q_c0 = residual_q(method_c(fv0, thr, k0, wt, rule, k_dur), fv0)
    q_c.update({k: v for k, v in q_c0.items() if k.endswith("_0")})
    q_b = residual_q(method_b(fvh, thr), fvh)

    # (d): train on train infants with mixed history lengths, early stopping inside the train set.
    ftr = features(days, events, train, look, [0, 1, 3, 7, 14])
    ftr = ftr.sample(min(len(ftr), 600_000), random_state=0)
    clf, regs = fit_d(ftr, fvh)

    # Test, by history length (cold start) and by age group.
    res["test"] = {}
    for Hs in (0, 1, 3, 7, 14):
        ft = features(days, events, test, look, [Hs])
        preds = {"a": interval(method_a(ft, episodes, bands), ft, None),
                 "b": interval(method_b(ft, thr), ft, q_b),
                 "c": interval(method_c(ft, thr, k0, wt, rule, k_dur), ft, q_c),
                 "d": method_d(ft, clf, regs)}
        common = preds["a"].pred.notna()
        block = {}
        for m, p in preds.items():
            block[m] = {"all": score(p, ft), "where_a_predicts": score(p[common], ft[common])}
            for lo, hi, name in AGE_GROUPS:
                sel = (ft.day >= lo) & (ft.day < hi)
                block[m][name] = score(p[sel], ft[sel])
        res["test"][f"H{Hs}"] = block
        print(Hs, {m: (b["all"]["mae"], b["all"]["median_ae"], b["all"]["within_30"]) for m, b in block.items()})
    res["model"] = {"history_days": H, "kind_rule": rule, "prior_weight": k0, "clock_weight": wt,
                    "duration_prior_weight": k_dur, "log_ratio_p10_p90": q_c, "bedtime_after": thr}
    norms = json.loads(Path(norms_json).read_text())
    norms["model"] = res["model"]
    norms["night_gap_minutes"] = json.loads((w / "extract_stats.json").read_text())["night_gap_minutes"]
    Path(norms_json).write_text(json.dumps(norms, indent=1, default=float))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "predict_results.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res["model"], default=float)[:2000])


if __name__ == "__main__":
    main(*sys.argv[1:4])
