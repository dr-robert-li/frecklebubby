"""Dataset readers: ICSD (cry detector) and the DeepInfant v2 folder (cry reason). Paths are always arguments."""

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .encoder import FRAME_SECONDS
from .frontend import SAMPLE_RATE

DETECTOR_CLASSES = ["cry", "snore"]  # "other" = neither
ICSD_LABELS = {"Infantcry": 0, "Snoring": 1}


def load_wav(path: Path) -> np.ndarray:
    """Mono float32 at 16 kHz. Resamples with a polyphase filter when the file has another rate."""
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SAMPLE_RATE:
        g = np.gcd(sr, SAMPLE_RATE)
        x = resample_poly(x, SAMPLE_RATE // g, sr // g).astype(np.float32)
    return x


def fix_length(x: np.ndarray, n: int = 10 * SAMPLE_RATE) -> np.ndarray:
    """Cut or zero-pad to n samples (ICSD clips are 10 s; a few are shorter)."""
    return x[:n] if len(x) >= n else np.pad(x, (0, n - len(x)))


# ---------------------------------------------------------------- ICSD

ICSD_SPLITS = {
    # split name: (audio folder, metadata file, kind)
    "train_weak": ("audio/train/weak", "metadata/train/weak.tsv", "weak"),
    "train_real": ("audio/train/real_strong_train", "metadata/train/real_strong_train.tsv", "strong"),
    "train_synth": ("audio/train/synth_strong_train", "metadata/train/synth_strong_train.tsv", "strong"),
    "val": ("audio/validation/strong_val", "metadata/validation/strong_val.tsv", "strong"),
    "test_real": ("audio/test/real_strong_test", "metadata/test/real_strong_test.tsv", "strong"),
    "test_synth": ("audio/test/synth_strong_test", "metadata/test/synth_strong_test.tsv", "strong"),
}


def icsd_index(root: Path, split: str) -> list[dict]:
    """[{name, path, weak: [0/1, 0/1] | None, events: [(onset, offset, class_idx)] | None}] sorted by name."""
    folder, meta, kind = ICSD_SPLITS[split]
    rows = list(csv.DictReader(open(root / meta), delimiter="\t"))
    out = []
    if kind == "weak":
        for r in rows:
            weak = [0, 0]
            for lab in r["event_labels"].split(","):
                weak[ICSD_LABELS[lab]] = 1
            out.append({"name": r["filename"], "weak": weak, "events": None})
    else:
        ev = defaultdict(list)
        for r in rows:
            ev[r["filename"]].append((float(r["onset"]), float(r["offset"]), ICSD_LABELS[r["event_label"]]))
        names = sorted({p.name for p in (root / folder).glob("*.wav")})
        out = [{"name": n, "weak": None, "events": ev.get(n, [])} for n in names]
    for o in out:
        o["path"] = root / folder / o["name"]
    return sorted(out, key=lambda o: o["name"])


def frame_targets(events: list, n_frames: int) -> np.ndarray:
    """(T, 2) 0/1: a frame is positive when its centre is inside an event of that class."""
    y = np.zeros((n_frames, len(DETECTOR_CLASSES)), dtype=np.float32)
    centres = (np.arange(n_frames) + 0.5) * FRAME_SECONDS
    for on, off, c in events:
        y[(centres >= on) & (centres < off), c] = 1.0
    return y


def clip_targets(item: dict) -> list[int]:
    if item["weak"] is not None:
        return item["weak"]
    return [int(any(c == k for _, _, c in item["events"])) for k in range(len(DETECTOR_CLASSES))]


# ---------------------------------------------------------------- DeepInfant v2 (cry reason)

FOLDER_CODES = {
    "belly_pain": "bp", "burping": "bu", "cold_hot": "ch", "discomfort": "dc", "hungry": "hu",
    "lonely": "lo", "scared": "sc", "tired": "ti", "unknown": "dk",
}
CODE_FOLDER = {v: k for k, v in FOLDER_CODES.items()}
# Rule: a class needs >= 15 clips after cleaning. cold_hot (7 clips, 3 recorders) is a kind of discomfort (the source
# data already filed 9 of its clips under discomfort), so it is merged. lonely (11 clips) has no close class: excluded.
# unknown is not a reason: excluded.
MERGE = {"cold_hot": "discomfort"}
EXCLUDE = {"unknown", "lonely"}
REASON_CLASSES = ["belly_pain", "burping", "discomfort", "hungry", "scared", "tired"]


def parse_name(name: str) -> dict:
    """`<36-char UUID>-<timestamp>-<app version>-<gender>-<age band>-<code>.wav`."""
    stem = name.rsplit(".", 1)[0]
    uuid, rest = stem[:36], stem[37:]
    parts = rest.split("-")
    return {"recorder": uuid.lower(), "timestamp": parts[0], "gender": parts[-3], "age": parts[-2], "code": parts[-1]}


def clean_reason_labels(root: Path) -> tuple[list[dict], list[str]]:
    """Deterministic label cleaning for Data/v2. Returns (kept rows, log lines).

    Rules, in order:
    1. One recording stored more than once (same recorder UUID and timestamp, or the same bytes): keep one copy,
       with the label that the filename code gives; if no copy has a folder that matches the code, drop all copies.
    2. Folder and filename code disagree (single copy): the filename code wins (the parent chose it in the app;
       the folder sort happened later). Codes that map to no class (`dk`) keep the folder label.
    3. `unknown` is excluded (it is not a reason).
    4. Classes with fewer than 15 clips: cold_hot is merged into discomfort; lonely is excluded.
    """
    log: list[str] = []
    files = sorted(p for p in root.glob("*/*.wav") if p.parent.name in FOLDER_CODES)
    # Group copies of one recording: same recorder UUID + timestamp (the same clip is stored once at 44.1 kHz and
    # once at 8 kHz in some folders), or byte-identical files under different names.
    sha = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    group: dict[Path, str] = {}
    first_by_sha: dict[str, str] = {}
    for p in files:
        m = parse_name(p.name)
        key = f"{m['recorder']}-{m['timestamp']}"
        group[p] = first_by_sha.setdefault(sha[p], key)
    by_rec: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        by_rec[group[p]].append(p)
    rows = []
    for h, paths in sorted(by_rec.items()):
        meta = parse_name(paths[0].name)
        code_label = CODE_FOLDER.get(meta["code"])
        if len({p.parent.name for p in paths}) == 1:
            paths = paths[:1]  # same recording twice in one folder
        if len(paths) > 1:
            match = [p for p in paths if p.parent.name == code_label]
            if not match:
                log.append(f"drop duplicate (no folder matches code {meta['code']}): {[p.parent.name for p in paths]}")
                continue
            log.append(f"duplicate kept once as {code_label}: {paths[0].name[:8]}… in {[p.parent.name for p in paths]}")
            p, label = match[0], code_label
        else:
            p = paths[0]
            label = p.parent.name
            if code_label and code_label != label:
                log.append(f"folder {label} -> code {code_label}: {p.name[:8]}…")
                label = code_label
        if label in EXCLUDE:
            continue
        label = MERGE.get(label, label)
        rows.append({"path": p, "label": label, "recorder": meta["recorder"], "recording": h})
    counts = defaultdict(int)
    for r in rows:
        counts[r["label"]] += 1
    log.append(f"kept {len(rows)} clips: {dict(sorted(counts.items()))}")
    return rows, log
