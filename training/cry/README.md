# Cry models training kit

This kit trains the two models of the Frecklebubby cry helper and exports them to ONNX:

- `cry_detector.onnx`: finds infant cry and snoring in a recording (frames of 0.32 s). Trained on ICSD.
- `cry_reason.onnx`: guesses a reason for a cry (hungry, tired, burping, belly pain, discomfort, scared).
  **Experimental.** The labels are parents' guesses, and the model is not much better than a fixed guess.

Both models use the same pretrained encoder: EfficientAT `mn10_as` (MobileNetV3 audio tagger, trained on AudioSet,
MIT licence, <https://github.com/fschmid56/EfficientAT>). The audio front end (resample, STFT, mel, log) is inside
the ONNX graphs. The app only decodes audio to 16 kHz mono float32 and runs the graphs.

This kit is a separate uv project. Torch and the other training packages are only here, not in the app.

## Data and licence rules

- **ICSD** (detector): Liu et al., "An Open-source Dataset for Infant Cry and Snoring Detection",
  arXiv:2408.10561. Licence CC BY-NC-SA 4.0 with gated terms. The authors gave the project owner permission to
  use it. Non-commercial use only. Do not copy the audio, or files made from single recordings, into the repository.
  Do not share the data. Share the detector weights only under the same non-commercial terms.
- **Cry-reason clips**: the `Data/v2` folder of the DeepInfant project (Donate-a-Cry lineage). The labels are
  parents' own guesses. Do not copy the audio into the repository.
- Never commit model weights or embeddings. The work folder and the output folder must be outside the repository.

## Install

On a machine without a GPU:

    cd training/cry
    uv sync --extra cpu

On a machine with an NVIDIA GPU (CUDA 12.8 wheels):

    cd training/cry
    uv sync --extra gpu

The first run downloads the encoder weights (19 MB) from the EfficientAT GitHub release to the torch hub cache.

## Commands

All paths are arguments. In the examples, `ICSD` is the folder that has `audio/` and `metadata/`, `REASON` is
`DeepInfant/Data/v2`, `WORK` is a work folder and `OUT` is the export folder.

| Command | What it does | Time (16-core CPU) |
|---|---|---|
| `uv run crykit compare-encoders --icsd ICSD --work WORK` | Linear-probe comparison of 3 encoders on an ICSD subset. Writes `WORK/encoder_comparison.json`. | 10 min |
| `uv run crykit prepare --icsd ICSD --reason-data REASON --work WORK` | Checks that all ICSD files exist. Cleans the reason labels and writes `WORK/reason_cleaning.log`. | 10 s |
| `uv run crykit embed --icsd ICSD --reason-data REASON --work WORK` | Runs the frozen encoder once on all clips. Writes `WORK/emb/*.npy` (float16, about 1 GB). | 13 min |
| `uv run crykit train-detector --icsd ICSD --work WORK` | Trains the detector head on ICSD train (weak, real strong and synthetic strong). Chooses the epoch, threshold and smoothing on validation. Reports on `real_strong_test` and `synth_strong_test`. Writes `WORK/detector.pt` and `WORK/detector_metrics.json`. | 30 min |
| `uv run crykit train-reason --work WORK` | Grouped cross-validation of the reason model (5 folds by recorder, 5 repeats), baselines, calibration, then the final fit on all clean data. Writes `WORK/reason_metrics.json` and `WORK/reason_head.npz`. | 3 min |
| `uv run crykit export --work WORK --out OUT` | Writes `cry_detector.onnx`, `cry_reason.onnx`, `model_card.json` and `NOTICE.txt` to `OUT`. Checks that ONNX gives the same output as torch. | 1 min |
| `uv run crykit all --icsd ICSD --reason-data REASON --work WORK --out OUT` | All steps above, except the encoder comparison. | 50 min |
| `uv run crykit all ... --smoke` | The same on 24 clips per ICSD split and 12 clips per reason class, in a temp work folder. Use it to check an install. | 1 min |
| `uv run pytest` | Kit tests: label cleaning rules, grouped folds, front-end parity with torch, ONNX parity. | 1 min |

### Fine-tune the encoder on a GPU

The default trains only the small heads on frozen embeddings. To fine-tune the encoder of the detector too:

    uv run crykit train-detector --icsd ICSD --work WORK --unfreeze --device cuda --epochs 20
    uv run crykit export --work WORK --out OUT

`--unfreeze` reads the audio files (not the cached embeddings). The encoder learning rate is 1e-5, the head
learning rate is 1e-3. The reason model always uses the frozen encoder (too little data to fine-tune).

**Not tested at full size.** On the CPU machine only the code path ran (a smoke run). Expect about
1–2 hours on one modern GPU for 20 epochs. Compare `WORK/detector_metrics.json` with the frozen run before you
install the result.

### The full sequence on the GPU machine

    cd training/cry
    uv sync --extra gpu
    uv run pytest
    uv run crykit all --icsd ICSD --reason-data REASON --work WORK --out OUT/frozen
    uv run crykit train-detector --icsd ICSD --work WORK --unfreeze --device cuda --epochs 20
    uv run crykit export --work WORK --out OUT/unfrozen

Then read the two `model_card.json` files and keep the better detector.

## Install the exported files in the app

1. Install the app with the `cry` extra (`uv sync --extra import --extra cry`; the container image has it) and
   make sure `ffmpeg` is installed (the container image has it).
2. Copy `cry_detector.onnx`, `cry_reason.onnx`, `model_card.json` and `NOTICE.txt` to `<DATA_DIR>/models/cry/`
   (in the container: `/data/models/cry/`), or set `CRY_MODEL_DIR` to their folder.
3. No restart is necessary. The app reads the files on the next request.

If the files are missing, the app still gives the "what to check" list from the logs. It says
"Sound analysis is not installed on this server."

## Rules in the code

- Reason label cleaning (`crykit/data.py`): one recording stored more than once (same recorder and timestamp, or
  the same bytes) is kept once, with the label of its filename code. When the folder and the filename code
  disagree, the code wins. `unknown` and `lonely` (11 clips) are excluded. `cold_hot` (7 clips) is merged into
  `discomfort`.
- The reason model sees each clip through a 4 kHz low-pass (in the graph), because most training clips are 8 kHz.
- The detector says "contains cry" when it finds 1 s or more of crying.
