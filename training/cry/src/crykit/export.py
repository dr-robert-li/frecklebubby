"""Export the two models to ONNX (audio front end inside the graph) and write model_card.json beside them."""

import datetime as dt
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from .data import DETECTOR_CLASSES, REASON_CLASSES
from .detector import IS_CRY_MIN_SECONDS
from .encoder import ENCODER_NAME, FRAME_SECONDS, Encoder
from .frontend import SAMPLE_RATE
from .heads import DetectorHead, DetectorModel, ReasonHead, ReasonModel

VERSION = "0.1"
ENCODER = {
    "name": f"EfficientAT {ENCODER_NAME} (MobileNetV3, AudioSet tagger, 4.9 M parameters)",
    "licence": "MIT (code and pretrained weights, published in the same repository's GitHub release)",
    "source_url": "https://github.com/fschmid56/EfficientAT",
    "weights_url": "https://github.com/fschmid56/EfficientAT/releases/download/v0.0.1/mn10_as_mAP_471.pt",
    "paper": "Schmid, Koutini, Widmer. Efficient Large-Scale Audio Tagging via Transformer-to-CNN Knowledge "
             "Distillation. ICASSP 2023. arXiv:2211.04772",
}
PAPER = {
    "source": "Liu et al., ICSD (arXiv:2408.10561), Tables 8 and 9, best row per column",
    "test_real": {"intersection_f1": {"cry": 0.8805, "snore": 0.8522}, "segment_f1_1s": {"cry": 0.9174, "snore": 0.8765}},
    "test_synth": {"intersection_f1": {"cry": 0.9878, "snore": 0.9901}, "segment_f1_1s": {"cry": 0.9786, "snore": 0.9722}},
}
NOTICE = """Frecklebubby cry models v{version}

cry_detector.onnx and cry_reason.onnx contain the EfficientAT mn10_as encoder
(https://github.com/fschmid56/EfficientAT, MIT licence, Copyright (c) 2022 Florian Schmid).

cry_detector.onnx: the head was trained on the ICSD dataset (Liu et al., arXiv:2408.10561,
CC BY-NC-SA 4.0). Non-commercial use only, with attribution. Because the weights are derived from ICSD,
share these weights only under the same terms.

cry_reason.onnx: the head was trained on crowd-labelled clips from the DeepInfant / Donate-a-Cry lineage.
The labels are parents' guesses. The model is experimental and is not a diagnosis.
"""


def _onnx(model: torch.nn.Module, path: Path, output: str) -> None:
    model.eval()
    x = torch.randn(1, SAMPLE_RATE * 10) * 0.1
    torch.onnx.export(model, (x,), str(path), input_names=["audio"], output_names=[output], opset_version=17,
                      dynamic_axes={"audio": {1: "samples"}, output: ({0: "frames"} if output == "frame_probs" else {})},
                      dynamo=False)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    for n in (SAMPLE_RATE * 10, SAMPLE_RATE * 3 + 123):
        x = (torch.randn(1, n) * 0.1)
        with torch.no_grad():
            want = model(x).numpy()
        got = sess.run(None, {"audio": x.numpy()})[0]
        err = float(np.abs(want - got).max())
        assert err < 1e-4, f"{path.name}: ONNX and torch differ by {err}"
        print(f"{path.name}: ONNX matches torch (max diff {err:.2e}, {n} samples)")


def export(work: Path, out: Path) -> dict:
    ckpt = torch.load(work / "detector.pt", map_location="cpu", weights_only=True)
    det_metrics = json.loads((work / "detector_metrics.json").read_text())
    reason_metrics = json.loads((work / "reason_metrics.json").read_text())
    rh = np.load(work / "reason_head.npz")

    out.mkdir(parents=True, exist_ok=True)
    det_encoder = Encoder()
    if ckpt["encoder"] is not None:
        det_encoder.load_state_dict(ckpt["encoder"])
    head = DetectorHead()
    head.load_state_dict(ckpt["head"])
    _onnx(DetectorModel(det_encoder, head), out / "cry_detector.onnx", "frame_probs")
    reason_head = ReasonHead(rh["mean"], rh["scale"], rh["weight"], rh["bias"])
    _onnx(ReasonModel(Encoder(), reason_head), out / "cry_reason.onnx", "reason_probs")

    pick = lambda s: {k: s[k]["mean"] for k in ("accuracy", "balanced_accuracy", "macro_f1", "macro_ovr_auc")}  # noqa: E731
    pick_sd = lambda s: {k: s[k]["sd"] for k in ("accuracy", "balanced_accuracy", "macro_f1", "macro_ovr_auc")}  # noqa: E731
    card = {
        "name": "frecklebubby-cry",
        "version": VERSION,
        "date": dt.date.today().isoformat(),
        "encoder": ENCODER,
        "input": {
            "sample_rate": SAMPLE_RATE, "channels": 1, "dtype": "float32", "range": [-1.0, 1.0],
            "name": "audio", "shape": [1, "samples"],
            "preprocessing": "Decode to 16 kHz mono float32 PCM (for example ffmpeg -ac 1 -ar 16000 -f f32le). Nothing "
                             "else: the 2x upsampling to 32 kHz, pre-emphasis, STFT (n_fft 1024, window 800, hop 320), "
                             "128 Kaldi mel bands (0-15000 Hz), log and (x + 4.5) / 5 normalisation are inside both "
                             "ONNX graphs. cry_reason.onnx also has a 4 kHz low-pass in the graph.",
            "min_seconds": 1.0, "max_seconds": 60.0,
        },
        "detector": {
            "file": "cry_detector.onnx", "output": "frame_probs", "output_shape": ["frames", 2],
            "labels": DETECTOR_CLASSES, "other": "a frame where no label is on",
            "frame_seconds": FRAME_SECONDS, "threshold": ckpt["threshold"], "median_frames": ckpt["median"],
            "is_cry_min_seconds": IS_CRY_MIN_SECONDS,
            "trained_on": "ICSD train (weak + real strong + synthetic strong), selected on ICSD validation",
            "unfrozen_encoder": det_metrics["unfrozen_encoder"],
            "metrics": {k: det_metrics[k] for k in ("test_real", "test_synth")},
            "paper": PAPER,
            "licence": "Head trained on ICSD (CC BY-NC-SA 4.0); non-commercial use, with attribution.",
        },
        "reason": {
            "file": "cry_reason.onnx", "output": "reason_probs", "labels": REASON_CLASSES,
            "experimental": True,
            "trained_on": f"{reason_metrics['clips']} cleaned clips from {reason_metrics['recorders']} recorders "
                          "(DeepInfant/Donate-a-Cry lineage, Data/v2)",
            "class_counts": reason_metrics["class_counts"],
            "evaluation": reason_metrics["cv"],
            "metrics": pick(reason_metrics["model_calibrated"]),
            "metrics_sd": pick_sd(reason_metrics["model_calibrated"]),
            "metrics_uncalibrated": pick(reason_metrics["model"]),
            "baselines": {"always_hungry": pick(reason_metrics["always_hungry"]),
                          "prior_sampler": pick(reason_metrics["prior_sampler"]),
                          "source_rate_only": pick(reason_metrics["source_rate_only"])},
            "confound": "All 'hungry' clips are 8 kHz recordings and all 'scared' clips are 44.1 kHz recordings. The "
                        "model may learn the recording source, not the cry. 'source_rate_only' shows how far the "
                        "sample rate alone gets.",
            "calibration": reason_metrics["calibration"],
            "licence": "Reason model trained on crowd-labelled clips from the DeepInfant/Donate-a-Cry lineage; "
                       "labels are parents' guesses. Experimental.",
        },
    }
    (out / "model_card.json").write_text(json.dumps(card, indent=2))
    (out / "NOTICE.txt").write_text(NOTICE.format(version=VERSION))
    print(f"wrote {out}")
    return card
