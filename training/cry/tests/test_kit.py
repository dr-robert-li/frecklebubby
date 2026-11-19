"""Kit tests: label cleaning, grouped folds, front-end parity, ONNX parity."""

import numpy as np
import soundfile as sf
import torch
from crykit import data
from crykit.encoder import Encoder, n_frames
from crykit.frontend import Frontend, kaldi_mel_banks, reference_mel
from crykit.reason import grouped_folds

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


def _wav(path, seed, sr=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.random.default_rng(seed).normal(0, 0.1, sr).astype(np.float32), sr)


def test_label_cleaning_rules(tmp_path):
    # same recording stored in two folders (different encodings): kept once, with the filename code
    _wav(tmp_path / "cold_hot" / f"{U1}-100-1.7-m-04-ch.wav", 1, 44100)
    _wav(tmp_path / "discomfort" / f"{U1}-100-1.7-m-04-ch.wav", 2)
    # folder and code disagree: code wins
    _wav(tmp_path / "discomfort" / f"{U1}-200-1.7-m-04-hu.wav", 3)
    # dk code keeps the folder label; unknown is excluded
    _wav(tmp_path / "unknown" / f"{U2}-300-1.7-f-26-dk.wav", 4)
    # lonely is excluded; tired is kept
    _wav(tmp_path / "lonely" / f"{U2}-400-1.7-f-26-lo.wav", 5)
    _wav(tmp_path / "tired" / f"{U2}-500-1.7-f-26-ti.wav", 6)
    # byte-identical file under two labels and names, no folder matches the code: dropped
    _wav(tmp_path / "burping" / f"{U2}-600-1.7-f-26-sc.wav", 7)
    _wav(tmp_path / "belly_pain" / f"{U2}-601-1.7-f-26-sc.wav", 7)

    rows, log = data.clean_reason_labels(tmp_path)
    got = sorted((r["path"].name.split("-")[5], r["label"]) for r in rows)
    assert got == [("100", "discomfort"), ("200", "hungry"), ("500", "tired")]
    assert any("drop duplicate" in line for line in log)
    assert all(r["recorder"] in (U1, U2) for r in rows)
    assert set(data.REASON_CLASSES) >= {r["label"] for r in rows}


def test_grouped_folds_keep_each_recorder_in_one_fold():
    rng = np.random.default_rng(0)
    g = np.repeat(np.arange(60), 4)
    y = rng.integers(0, 3, len(g))
    x = rng.normal(size=(len(g), 2))
    for seed in range(3):
        folds = grouped_folds(x, y, g, 5, seed)
        seen = {}
        for f, (_, te) in enumerate(folds):
            for grp in set(g[te]):
                assert seen.setdefault(grp, f) == f
        assert len(seen) == 60


def test_mel_banks_match_torchaudio():
    import torchaudio

    want, _ = torchaudio.compliance.kaldi.get_mel_banks(128, 1024, 32000.0, 0.0, 15000.0, 100.0, -500.0, 1.0)
    np.testing.assert_allclose(kaldi_mel_banks()[:, :-1], want.numpy(), atol=5e-5)  # torchaudio works in float32


def test_frontend_matches_reference_stft():
    fe = Frontend()
    wav = torch.randn(2, 16000 * 3) * 0.1
    got = fe(wav)[:, 0]
    want = reference_mel(fe.upsample(wav))
    assert got.shape == want.shape
    assert (got - want).abs().max() < 1e-3


def test_frame_count_and_onnx_parity(tmp_path):
    from crykit.export import _onnx
    from crykit.heads import DetectorHead, DetectorModel

    enc = Encoder().eval()
    for n in (16000 * 10, 16000 * 7, 16000 * 3 + 5):
        with torch.no_grad():
            assert enc(torch.zeros(1, n)).shape[1] == n_frames(n)
    _onnx(DetectorModel(enc, DetectorHead()), tmp_path / "d.onnx", "frame_probs")  # asserts max diff < 1e-4
