"""Compute frozen encoder embeddings once and cache them on disk (float16)."""

import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from .data import ICSD_SPLITS, clean_reason_labels, fix_length, icsd_index, load_wav
from .encoder import Encoder
from .frontend import LowPass
from .heads import reason_embedding


def embed_icsd(icsd: Path, work: Path, limit: int | None = None, batch: int = 32) -> None:
    """work/emb/<split>.npy (N, 32, 960) float16 + <split>.json (names). limit: first N clips per split (smoke)."""
    out = work / "emb"
    out.mkdir(parents=True, exist_ok=True)
    enc = Encoder().eval()
    for split in ICSD_SPLITS:
        items = icsd_index(icsd, split)[:limit]
        t0 = time.time()
        chunks = []
        with torch.no_grad():
            for i in range(0, len(items), batch):
                wav = torch.from_numpy(np.stack([fix_length(load_wav(it["path"])) for it in items[i:i + batch]]))
                chunks.append(enc(wav).numpy().astype(np.float16))
        np.save(out / f"{split}.npy", np.concatenate(chunks))
        (out / f"{split}.json").write_text(json.dumps([it["name"] for it in items]))
        print(f"{split}: {len(items)} clips in {time.time() - t0:.0f} s", flush=True)


def embed_reason(reason_dir: Path, work: Path, limit: int | None = None) -> None:
    """limit: clips per class (smoke). work/emb/reason.npy (N, 960) + reason.json (label, recorder, file name) + reason_cleaning.log."""
    out = work / "emb"
    out.mkdir(parents=True, exist_ok=True)
    rows, log = clean_reason_labels(reason_dir)
    if limit:  # smoke: a few clips of each class
        rows = [r for c in sorted({r["label"] for r in rows}) for r in [x for x in rows if x["label"] == c][:limit]]
    (out / "reason_cleaning.log").write_text("\n".join(log) + "\n")
    enc, lp = Encoder().eval(), LowPass()
    embs = []
    with torch.no_grad():
        for r in rows:
            embs.append(reason_embedding(enc, lp, torch.from_numpy(load_wav(r["path"]))[None])[0].numpy())
    np.save(out / "reason.npy", np.stack(embs).astype(np.float32))
    (out / "reason.json").write_text(json.dumps(
        [{"label": r["label"], "recorder": r["recorder"], "file": r["path"].name,
          "source_rate": sf.info(str(r["path"])).samplerate} for r in rows]))
    print(f"reason: {len(rows)} clips", flush=True)
