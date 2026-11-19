"""Cry-reason model: frozen clip embeddings + multinomial logistic regression, leakage-free evaluation.

Evaluation: StratifiedGroupKFold (5 folds) grouped by recorder UUID, repeated with 5 seeds. The regularisation C is
chosen inside each training fold (grouped 3-fold). Calibration: per-class bias + one temperature on the logits,
fitted on out-of-fold logits; its own effect is measured by a second grouped cross-fit (no fold sees its own labels).
Baselines: always "hungry", and a sampler that draws labels from the training-fold class frequencies.
Confound check: "source_rate_only" knows only the original sample rate of the file (8 kHz or 44.1 kHz) and predicts
the most common training-fold class for that rate. In this data all "hungry" clips are 8 kHz and all "scared" clips
are 44.1 kHz, so part of what any model learns can be the recording source, not the cry.
"""

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import log_softmax, softmax
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler

from .data import REASON_CLASSES

C_GRID = (0.001, 0.01, 0.1)
FOLDS, REPEATS = 5, 5


def grouped_folds(x, y, g, folds: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Stratified folds where all clips of one recorder are in the same fold."""
    return list(StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed).split(x, y, g))


def load(work: Path):
    rows = json.loads((work / "emb" / "reason.json").read_text())
    x = np.load(work / "emb" / "reason.npy")
    y = np.array([REASON_CLASSES.index(r["label"]) for r in rows])
    g = np.array([r["recorder"] for r in rows])
    rate = np.array([r.get("source_rate", 0) for r in rows])
    return x, y, g, rate


def fit(x, y, c):
    sc = StandardScaler().fit(x)
    m = LogisticRegression(C=c, class_weight="balanced", max_iter=5000).fit(sc.transform(x), y)
    return sc, m


def logits(sc, m, x, k):
    """Logits for all k classes (a class missing from the training fold gets -inf -> probability 0)."""
    z = np.full((len(x), k), -1e9)
    z[:, m.classes_] = m.decision_function(sc.transform(x)) if len(m.classes_) > 2 else np.c_[
        -m.decision_function(sc.transform(x)), m.decision_function(sc.transform(x))]
    return z


def choose_c(x, y, g, seed=0) -> float:
    k = len(REASON_CLASSES)
    best, best_c = -1.0, C_GRID[0]
    folds = list(GroupKFold(n_splits=3, shuffle=True, random_state=seed).split(x, y, g))
    for c in C_GRID:
        f = []
        for tr, te in folds:
            sc, m = fit(x[tr], y[tr], c)
            f.append(f1_score(y[te], logits(sc, m, x[te], k).argmax(1), average="macro", labels=range(k),
                              zero_division=0))
        if np.mean(f) > best:
            best, best_c = float(np.mean(f)), c
    return best_c


def fit_calibration(z, y) -> tuple[float, np.ndarray]:
    """Temperature T and per-class bias b minimising NLL of softmax(z / T + b)."""
    k = z.shape[1]
    z = np.clip(z, -50, 50)

    def nll(p):
        t, b = np.exp(p[0]), p[1:]
        return -log_softmax(z / t + b, axis=1)[np.arange(len(y)), y].mean()

    r = minimize(nll, np.zeros(k + 1), method="L-BFGS-B")
    return float(np.exp(r.x[0])), r.x[1:]


def apply_calibration(z, t, b):
    return softmax(np.clip(z, -50, 50) / t + b, axis=1)


def ece(p, y, bins=10) -> float:
    conf, pred = p.max(1), p.argmax(1)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(e)


def scores(y, p, k) -> dict:
    pred = p.argmax(1)
    prec, rec, _, _ = precision_recall_fscore_support(y, pred, labels=range(k), zero_division=0)
    aucs = [roc_auc_score(y == c, p[:, c]) for c in range(k) if 0 < (y == c).sum() < len(y)]
    return {"macro_f1": f1_score(y, pred, average="macro", labels=range(k), zero_division=0),
            "balanced_accuracy": balanced_accuracy_score(y, pred), "accuracy": float((pred == y).mean()),
            "macro_ovr_auc": float(np.mean(aucs)), "precision": prec, "recall": rec,
            "confusion": confusion_matrix(y, pred, labels=range(k))}


def summary(runs: list[dict]) -> dict:
    """Mean and standard deviation over folds (scalars) and mean over folds (per class, confusion summed)."""
    out = {}
    for key in ("macro_f1", "balanced_accuracy", "accuracy", "macro_ovr_auc"):
        v = np.array([r[key] for r in runs])
        out[key] = {"mean": round(float(v.mean()), 4), "sd": round(float(v.std()), 4),
                    "min": round(float(v.min()), 4), "max": round(float(v.max()), 4)}
    for key in ("precision", "recall"):
        v = np.array([r[key] for r in runs])
        out[key] = {c: {"mean": round(float(v[:, i].mean()), 4), "sd": round(float(v[:, i].std()), 4)}
                    for i, c in enumerate(REASON_CLASSES)}
    out["confusion_rows_true_cols_pred"] = (np.sum([r["confusion"] for r in runs], axis=0) // REPEATS).tolist()
    return out


def evaluate(work: Path, out: Path, folds=FOLDS, repeats=REPEATS) -> dict:
    x, y, g, rate = load(work)
    k = len(REASON_CLASSES)
    hungry = REASON_CLASSES.index("hungry")
    runs = {"model": [], "model_calibrated": [], "always_hungry": [], "prior_sampler": [], "source_rate_only": []}
    group_check = []
    oof = []
    for rep in range(repeats):
        rng = np.random.default_rng(rep)
        z_oof = np.zeros((len(y), k))
        split = grouped_folds(x, y, g, folds, rep)
        group_check.append(max(len({f for f, (_, te) in enumerate(split) if gr in set(g[te])}) for gr in set(g)))
        for tr, te in split:
            c = choose_c(x[tr], y[tr], g[tr], seed=rep)
            sc, m = fit(x[tr], y[tr], c)
            z = logits(sc, m, x[te], k)
            z_oof[te] = z
            runs["model"].append(scores(y[te], softmax(np.clip(z, -50, 50), axis=1), k))
            const = np.zeros((len(te), k))
            const[:, hungry] = 1.0
            runs["always_hungry"].append(scores(y[te], const, k))
            prior = np.bincount(y[tr], minlength=k) / len(tr)
            draws = rng.choice(k, size=len(te), p=prior)
            sampled = np.tile(prior * 0.5, (len(te), 1))  # probabilities = priors; argmax = the drawn label
            sampled[np.arange(len(te)), draws] += 1.0
            runs["prior_sampler"].append(scores(y[te], sampled / sampled.sum(1, keepdims=True), k))
            by_rate = {r: np.bincount(y[tr][rate[tr] == r], minlength=k) for r in set(rate)}
            src = np.array([by_rate[r] / max(1, by_rate[r].sum()) for r in rate[te]])
            runs["source_rate_only"].append(scores(y[te], src + 1e-6 * prior, k))
        # Calibration measured by a grouped cross-fit on this repeat's out-of-fold logits.
        for tr, te in split:
            t, b = fit_calibration(z_oof[tr], y[tr])
            runs["model_calibrated"].append(scores(y[te], apply_calibration(z_oof[te], t, b), k))
        oof.append(z_oof)

    # Calibration quality (expected calibration error, 10 bins) on the pooled out-of-fold predictions.
    z_all, y_all = np.concatenate(oof), np.tile(y, repeats)
    t_all, b_all = fit_calibration(z_all, y_all)
    cal = {"ece_raw_softmax": round(ece(softmax(np.clip(z_all, -50, 50), axis=1), y_all), 4),
           "ece_calibrated_in_sample": round(ece(apply_calibration(z_all, t_all, b_all), y_all), 4),
           "temperature": round(t_all, 4), "bias": [round(float(v), 4) for v in b_all]}

    # Final model on all cleaned data.
    c_final = choose_c(x, y, g)
    sc, m = fit(x, y, c_final)
    out.mkdir(parents=True, exist_ok=True)
    w = m.coef_ / t_all
    b = m.intercept_ / t_all + b_all
    np.savez(out / "reason_head.npz", mean=sc.mean_, scale=sc.scale_, weight=w, bias=b)
    counts = np.bincount(y, minlength=k)
    result = {
        "classes": REASON_CLASSES, "clips": int(len(y)), "recorders": int(len(set(g))),
        "class_counts": dict(zip(REASON_CLASSES, counts.tolist(), strict=True)),
        "cv": f"StratifiedGroupKFold({folds}) by recorder UUID x {repeats} repeats; C chosen inside each training fold",
        "max_folds_per_recorder_in_one_repeat": int(max(group_check)),
        "final_C": c_final, "calibration": cal,
        **{name: summary(r) for name, r in runs.items()},
    }
    (out / "reason_metrics.json").write_text(json.dumps(result, indent=2))
    for name in runs:
        s = result[name]
        print(f"{name:18s} macroF1 {s['macro_f1']['mean']:.3f}±{s['macro_f1']['sd']:.3f}  "
              f"balAcc {s['balanced_accuracy']['mean']:.3f}±{s['balanced_accuracy']['sd']:.3f}  "
              f"acc {s['accuracy']['mean']:.3f}  AUC {s['macro_ovr_auc']['mean']:.3f}±{s['macro_ovr_auc']['sd']:.3f}")
    return result
