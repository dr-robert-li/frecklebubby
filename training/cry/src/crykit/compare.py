"""Quick encoder comparison: frame-level linear probe on an ICSD subset + CPU speed + ONNX export check.

Candidates (all permissive licences, checked on the model pages; see README):
  mn10_as     EfficientAT MobileNetV3, AudioSet, 4.9 M params, MIT
  ced-tiny    mispeech/ced-tiny (CED, AudioSet), 5.5 M params, Apache-2.0
  distilhubert ntu-spml/distilhubert (speech SSL, LibriSpeech), 23.5 M params, Apache-2.0
"""

import io
import json
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from .data import fix_length, frame_targets, icsd_index, load_wav
from .encoder import Encoder


def pool_time(x: torch.Tensor, k: int) -> torch.Tensor:
    """(B, T, C) -> (B, T // k, C) average."""
    t = x.shape[1] // k * k
    return x[:, :t].reshape(x.shape[0], t // k, k, x.shape[2]).mean(2)


class HFEncoder(torch.nn.Module):
    def __init__(self, name: str):
        super().__init__()
        from transformers import AutoFeatureExtractor, AutoModel, AutoModelForAudioClassification

        self.name = name
        self.fe = AutoFeatureExtractor.from_pretrained(name, trust_remote_code=True)
        if "ced" in name:
            self.model = AutoModelForAudioClassification.from_pretrained(name, trust_remote_code=True).encoder.eval()
        else:
            self.model = AutoModel.from_pretrained(name).eval()

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        inp = self.fe(list(wav.numpy()), sampling_rate=16000, return_tensors="pt")
        x = inp["input_values"]
        if "ced" in self.name:
            h = self.model(x).logits  # (B, 4*T, 192), frequency-major
            h = h.reshape(h.shape[0], 4, -1, h.shape[-1]).mean(1)
            return pool_time(h, 2)  # 0.16 s -> 0.32 s
        h = self.model(input_values=x).last_hidden_state  # 20 ms frames
        return pool_time(h, 16)


def build(name: str) -> torch.nn.Module:
    return Encoder("mn10_as").eval() if name == "mn10_as" else HFEncoder(name)


def embed(enc, items, batch=16):
    out = []
    with torch.no_grad():
        for i in range(0, len(items), batch):
            wav = torch.from_numpy(np.stack([fix_length(load_wav(it["path"])) for it in items[i:i + batch]]))
            out.append(enc(wav).numpy())
    return np.concatenate(out)


def to_xy(emb, items):
    xs, ys = [], []
    for e, it in zip(emb, items, strict=True):
        y = frame_targets(it["events"], e.shape[0])
        xs.append(e)
        ys.append(np.where(y[:, 0] > 0, 1, np.where(y[:, 1] > 0, 2, 0)))  # 0 other, 1 cry, 2 snore
    return np.concatenate(xs), np.concatenate(ys)


def speed(enc, threads: int) -> float:
    torch.set_num_threads(threads)
    x = torch.randn(1, 160000) * 0.1
    with torch.no_grad():
        enc(x)
        t = time.perf_counter()
        for _ in range(5):
            enc(x)
    return (time.perf_counter() - t) / 5


def onnx_ok(enc) -> str:
    if isinstance(enc, HFEncoder):
        enc = enc.model  # the feature extractor stays outside the graph for HF models
        x = torch.randn(1, 64, 1001) if "ced" in enc.__class__.__name__.lower() else torch.randn(1, 160000)
    else:
        x = torch.randn(1, 160000)
    try:
        torch.onnx.export(enc, (x,), io.BytesIO(), opset_version=17, dynamo=False)
        return "ok"
    except Exception as e:  # report, do not stop the comparison
        return f"failed: {type(e).__name__}: {str(e)[:120]}"


def run(icsd: Path, out: Path, names: list[str], n_train_synth=500, n_val_synth=300, seed=0):
    rng = np.random.default_rng(seed)
    train = icsd_index(icsd, "train_real") + list(rng.choice(icsd_index(icsd, "train_synth"), n_train_synth, replace=False))
    val = icsd_index(icsd, "val")
    val_real = [v for v in val if v["name"].startswith("strong_")]
    val_synth = list(rng.choice([v for v in val if v["name"].startswith("synth_")], n_val_synth, replace=False))
    results = {}
    for name in names:
        enc = build(name)
        t0 = time.perf_counter()
        torch.set_num_threads(16)
        e_train, e_vr, e_vs = embed(enc, train), embed(enc, val_real), embed(enc, val_synth)
        embed_s = time.perf_counter() - t0
        xtr, ytr = to_xy(e_train, train)
        sc = StandardScaler().fit(xtr)
        clf = LogisticRegression(max_iter=3000, C=0.1).fit(sc.transform(xtr), ytr)
        r = {"dim": int(xtr.shape[1]), "embed_seconds_all_clips_16_threads": round(embed_s, 1)}
        for tag, e, items in [("val_real", e_vr, val_real), ("val_synth", e_vs, val_synth)]:
            x, y = to_xy(e, items)
            p = clf.predict(sc.transform(x))
            r[f"{tag}_frame_macro_f1_cry_snore"] = round(float(f1_score(y, p, labels=[1, 2], average="macro")), 4)
            r[f"{tag}_frame_f1_cry"] = round(float(f1_score(y == 1, p == 1)), 4)
            clip_y = [int(any(c == 0 for _, _, c in it["events"])) for it in items]
            clip_s = [clf.predict_proba(sc.transform(ei))[:, 1].max() for ei in e]
            r[f"{tag}_clip_auc_cry"] = round(float(roc_auc_score(clip_y, clip_s)), 4)
        r["cpu_seconds_per_10s_1_thread"] = round(speed(enc, 1), 3)
        r["cpu_seconds_per_10s_4_threads"] = round(speed(enc, 4), 3)
        r["onnx_export"] = onnx_ok(enc)
        results[name] = r
        print(name, json.dumps(r), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    meta = {"train_clips": len(train), "val_real_clips": len(val_real), "val_synth_clips": len(val_synth),
            "probe": "multinomial logistic regression (C=0.1) on standardised 0.32 s frame embeddings",
            "results": results}
    (out / "encoder_comparison.json").write_text(json.dumps(meta, indent=2))
    return meta
