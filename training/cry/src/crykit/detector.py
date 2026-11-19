"""Cry / snore detector: train on ICSD train (weak + real strong + synthetic strong), select on validation,
report on real_strong_test and synth_strong_test separately.

Frozen mode (default): reads cached embeddings. --unfreeze: reads audio and fine-tunes the encoder too (GPU).
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.ndimage import median_filter

from .data import clip_targets, fix_length, frame_targets, icsd_index, load_wav
from .encoder import FRAME_SECONDS, Encoder
from .heads import DetectorHead, clip_pool

TRAIN_SPLITS = ["train_weak", "train_real", "train_synth"]
TEST_SPLITS = ["test_real", "test_synth"]
ICSD_NAMES = {0: "Infantcry", 1: "Snoring"}
IS_CRY_MIN_SECONDS = 1.0  # a clip "contains infant cry" when the detected cry lasts at least this long


# ---------------------------------------------------------------- data


def load_split(icsd: Path, work: Path | None, split: str, limit: int | None = None):
    """(items, X or None). X: cached embeddings (N, T, 960) when work is given."""
    items = icsd_index(icsd, split)[:limit]
    if work is None:
        return items, None
    names = json.loads((work / "emb" / f"{split}.json").read_text())
    x = np.load(work / "emb" / f"{split}.npy", mmap_mode="r")
    pos = {n: i for i, n in enumerate(names)}
    items = [it for it in items if it["name"] in pos]
    return items, np.asarray(x[[pos[it["name"]] for it in items]], dtype=np.float32)


# ---------------------------------------------------------------- post-processing and metrics


def events_from_probs(p: np.ndarray, threshold: float, median: int) -> list[tuple[float, float, int]]:
    """Frame probs (T, 2) -> [(onset, offset, class)] in seconds."""
    out = []
    for c in range(p.shape[1]):
        on = p[:, c] >= threshold
        if median > 1:
            on = median_filter(on.astype(np.uint8), size=median, mode="nearest").astype(bool)
        t = 0
        while t < len(on):
            if on[t]:
                s = t
                while t < len(on) and on[t]:
                    t += 1
                out.append((s * FRAME_SECONDS, t * FRAME_SECONDS, c))
            t += 1
    return out


def _df(rows):
    return pd.DataFrame(rows, columns=["filename", "onset", "offset", "event_label"])


def evaluate(items, probs, threshold: float, median: int) -> dict:
    """Segment-based F1 (1 s, sed_eval), intersection-based F1 (psds_eval, DTC 0.5 GTC 0.5 CTTC 0.3, same as the
    ICSD paper), event-based F1 (sed_eval, collar 200 ms), and clip-level "contains infant cry" precision/recall."""
    import sed_eval
    from psds_eval import PSDSEval

    ref, est, clip = [], [], {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for it, p in zip(items, probs, strict=True):
        ev = events_from_probs(p, threshold, median)
        ref += [(it["name"], on, off, ICSD_NAMES[c]) for on, off, c in it["events"]]
        est += [(it["name"], on, min(off, 10.0), ICSD_NAMES[c]) for on, off, c in ev]
        truth = any(c == 0 for *_, c in it["events"])
        pred = sum(off - on for on, off, c in ev if c == 0) >= IS_CRY_MIN_SECONDS
        clip[("t" if truth == pred else "f") + ("p" if pred else "n")] += 1
    ref_df, est_df = _df(ref), _df(est)
    labels = list(ICSD_NAMES.values())
    seg = sed_eval.sound_event.SegmentBasedMetrics(event_label_list=labels, time_resolution=1.0)
    evm = sed_eval.sound_event.EventBasedMetrics(event_label_list=labels, t_collar=0.2, percentage_of_length=0.2)
    for it in items:
        r = ref_df[ref_df.filename == it["name"]].to_dict("records")
        e = est_df[est_df.filename == it["name"]].to_dict("records")
        for x in r + e:
            x["file"] = x["filename"]
        seg.evaluate(reference_event_list=r, estimated_event_list=e)
        evm.evaluate(reference_event_list=r, estimated_event_list=e)
    sr, er = seg.results_class_wise_metrics(), evm.results_class_wise_metrics()
    durations = pd.DataFrame({"filename": [it["name"] for it in items], "duration": [10.0] * len(items)})
    psds = PSDSEval(dtc_threshold=0.5, gtc_threshold=0.5, cttc_threshold=0.3, ground_truth=ref_df, metadata=durations)
    inter_macro, inter_cls = psds.compute_macro_f_score(est_df) if len(est_df) else (0.0, {k: 0.0 for k in labels})
    prec = clip["tp"] / max(1, clip["tp"] + clip["fp"])
    rec = clip["tp"] / max(1, clip["tp"] + clip["fn"])
    r4 = lambda v: round(float(v), 4)  # noqa: E731
    return {
        "clips": len(items),
        "segment_f1_1s": {"cry": r4(sr["Infantcry"]["f_measure"]["f_measure"]),
                          "snore": r4(sr["Snoring"]["f_measure"]["f_measure"])},
        "intersection_f1": {"cry": r4(inter_cls.get("Infantcry", 0)), "snore": r4(inter_cls.get("Snoring", 0)),
                            "macro": r4(inter_macro)},
        "event_f1_collar_200ms": {"cry": r4(er["Infantcry"]["f_measure"]["f_measure"]),
                                  "snore": r4(er["Snoring"]["f_measure"]["f_measure"])},
        "clip_contains_cry": {"precision": r4(prec), "recall": r4(rec), **clip,
                              "rule": f"detected cry >= {IS_CRY_MIN_SECONDS} s"},
    }


# ---------------------------------------------------------------- training


def _batches(n, size, rng):
    idx = rng.permutation(n)
    return [idx[i:i + size] for i in range(0, n, size)]


def fetch(x, idx) -> np.ndarray:
    """Rows of cached embeddings, or (unfrozen mode) audio loaded from a list of paths."""
    if isinstance(x, np.ndarray):
        return x[idx]
    return np.stack([fix_length(load_wav(x[i])) for i in idx]).astype(np.float32)


def predict(head, x, encoder=None, batch=64) -> np.ndarray:
    head.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            xb = torch.as_tensor(fetch(x, list(range(i, min(i + batch, len(x))))))
            if encoder is not None:
                encoder.eval()
                xb = encoder(xb)
            out.append(head(xb).numpy())
    return np.concatenate(out)


def train(icsd: Path, work: Path, out: Path, epochs: int = 40, unfreeze: bool = False, limit: int | None = None,
          seed: int = 0, device: str = "cpu", batch: int = 64, lr: float = 1e-3, encoder_lr: float = 1e-5) -> dict:
    """Train, select epoch + threshold + median filter on validation, report on test. Writes out/detector.pt and
    out/detector_metrics.json."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    src = None if unfreeze else work

    def xy(split):
        items, x = load_split(icsd, src, split, limit)
        return items, (x if x is not None else [it["path"] for it in items])  # unfrozen: audio paths

    tr_items, tr_x = [], []
    for sp in TRAIN_SPLITS:
        it, x = xy(sp)
        tr_items += it
        tr_x.append(x)
    tr_x = np.concatenate(tr_x) if src is not None else [p for x in tr_x for p in x]
    va_items, va_x = xy("val")

    head = DetectorHead().to(device)
    encoder = Encoder().to(device) if unfreeze else None
    params = [{"params": head.parameters(), "lr": lr}]
    if encoder is not None:
        params.append({"params": encoder.features.parameters(), "lr": encoder_lr})
    opt = torch.optim.AdamW(params, weight_decay=1e-3)
    bce = torch.nn.BCELoss()
    n_frames = 32
    strong = np.array([it["events"] is not None for it in tr_items])
    y_frame = np.stack([frame_targets(it["events"] or [], n_frames) for it in tr_items])
    y_clip = np.array([clip_targets(it) for it in tr_items], dtype=np.float32)

    best = {"score": -1.0}
    t0 = time.time()
    for ep in range(epochs):
        head.train()
        if encoder is not None:
            encoder.train()
        for b in _batches(len(tr_items), batch, rng):
            xb = torch.as_tensor(fetch(tr_x, b)).to(device)
            if encoder is not None:
                xb = encoder(xb)
            p = head(xb)
            loss = torch.zeros((), device=device)
            sb = torch.as_tensor(strong[b]).to(device)
            if sb.any():
                loss = loss + bce(p[sb], torch.as_tensor(y_frame[b]).to(device)[sb])
            if (~sb).any():
                loss = loss + bce(clip_pool(p[~sb]), torch.as_tensor(y_clip[b]).to(device)[~sb])
            opt.zero_grad()
            loss.backward()
            opt.step()
        probs = predict(head.cpu(), va_x, encoder.cpu() if encoder is not None else None)
        head.to(device)
        if encoder is not None:
            encoder.to(device)
        # Selection score: mean of frame-level F1 at 0.5 for cry and snore (fast; full metrics only for the best).
        yv = np.concatenate([frame_targets(it["events"], p.shape[0]) for it, p in zip(va_items, probs, strict=True)])
        pv = np.concatenate(list(probs)) >= 0.5
        f1 = [2 * (pv[:, c] & (yv[:, c] > 0)).sum() / max(1, pv[:, c].sum() + (yv[:, c] > 0).sum()) for c in range(2)]
        score = float(np.mean(f1))
        print(f"epoch {ep + 1}/{epochs} val frame F1 cry {f1[0]:.3f} snore {f1[1]:.3f} ({time.time() - t0:.0f} s)",
              flush=True)
        if score > best["score"]:
            best = {"score": score, "epoch": ep + 1,
                    "head": {k: v.detach().cpu().clone() for k, v in head.state_dict().items()},
                    "encoder": ({k: v.detach().cpu().clone() for k, v in encoder.state_dict().items()}
                                if encoder is not None else None)}
    head.load_state_dict(best["head"])
    head.cpu()
    if encoder is not None:
        encoder.load_state_dict(best["encoder"])
        encoder.cpu()
    va_probs = predict(head, va_x, encoder)

    # Post-processing chosen on validation (real and synthetic together), by mean intersection F1.
    grid = [(th, m) for th in (0.3, 0.4, 0.5, 0.6, 0.7) for m in (1, 3, 5)]
    scores = {(th, m): evaluate(va_items, va_probs, th, m)["intersection_f1"]["macro"] for th, m in grid}
    threshold, median = max(scores, key=scores.get)
    result = {"selected": {"epoch": best["epoch"], "threshold": threshold, "median_frames": median,
                           "val_intersection_f1_macro": scores[(threshold, median)]},
              "unfrozen_encoder": unfreeze, "train_clips": len(tr_items), "val_clips": len(va_items),
              "train_seconds": round(time.time() - t0), "limit_per_split": limit}
    for sp in TEST_SPLITS:
        items, x = xy(sp)
        result[sp] = evaluate(items, predict(head, x, encoder), threshold, median)
    out.mkdir(parents=True, exist_ok=True)
    torch.save({"head": head.state_dict(), "encoder": encoder.state_dict() if encoder is not None else None,
                "threshold": threshold, "median": median}, out / "detector.pt")
    (out / "detector_metrics.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("selected", *TEST_SPLITS)}, indent=2))
    return result

