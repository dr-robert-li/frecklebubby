# Notice for the cry models

The cry model files are not in this repository. `crykit export` writes this text as `NOTICE.txt` next to them.
Keep it with the files when you copy them.

- **Encoder** (in both `cry_detector.onnx` and `cry_reason.onnx`): EfficientAT `mn10_as`,
  <https://github.com/fschmid56/EfficientAT>, MIT licence, Copyright (c) 2022 Florian Schmid. The model code in
  `src/crykit/efficientat/` is copied from that repository (only the import paths changed); its licence is in
  `src/crykit/efficientat/LICENSE`.
- **Detector head** (`cry_detector.onnx`): trained on ICSD (Liu et al., arXiv:2408.10561), CC BY-NC-SA 4.0 and
  gated terms. Used with the dataset authors' permission given to the project owner. Non-commercial use only. Do
  not share the ICSD data. Share these weights only under the same non-commercial terms.
- **Reason head** (`cry_reason.onnx`): trained on crowd-labelled clips from the DeepInfant / Donate-a-Cry lineage.
  The labels are parents' guesses. Experimental; not a diagnosis.
