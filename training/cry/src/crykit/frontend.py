"""Audio front end that lives INSIDE the exported ONNX graph.

Input: mono float32 waveform at 16 kHz, values in [-1, 1].
Steps: 2x upsample to 32 kHz (fixed FIR) -> pre-emphasis -> STFT as a fixed conv -> power -> Kaldi mel banks
-> log -> (x + 4.5) / 5. These are the EfficientAT eval-mode settings (n_fft 1024, win 800, hop 320, 128 mels).
Only Conv1d, ConvTranspose1d, Pad, MatMul and elementwise ops, so every ONNX runtime runs it the same way.
"""

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

SAMPLE_RATE = 16000  # model input rate
ENCODER_RATE = 32000  # EfficientAT rate
N_FFT, WIN, HOP, N_MELS = 1024, 800, 320, 128
FMIN, FMAX = 0.0, ENCODER_RATE // 2 - 1000  # EfficientAT: fmax = sr/2 - fmax_aug_range/2
UPSAMPLE_TAPS = 63


def lowpass_taps(n: int = UPSAMPLE_TAPS) -> np.ndarray:
    """Windowed-sinc half-band low-pass for 2x upsampling (cut-off at the old Nyquist), gain 2."""
    t = np.arange(n) - (n - 1) / 2
    h = np.sinc(t / 2) * np.blackman(n)
    return (2 * h / h.sum()).astype(np.float32)


def kaldi_mel_banks(n_mels=N_MELS, n_fft=N_FFT, sr=ENCODER_RATE, fmin=FMIN, fmax=FMAX) -> np.ndarray:
    """Same numbers as torchaudio.compliance.kaldi.get_mel_banks (no VTLN warp), padded to n_fft//2+1 bins."""
    num_bins = n_fft // 2
    fft_bin_width = sr / n_fft

    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    mel_low, mel_high = mel(fmin), mel(fmax)
    delta = (mel_high - mel_low) / (n_mels + 1)
    b = np.arange(n_mels, dtype=np.float64)[:, None]
    left, center, right = mel_low + b * delta, mel_low + (b + 1) * delta, mel_low + (b + 2) * delta
    m = mel(fft_bin_width * np.arange(num_bins, dtype=np.float64))[None, :]
    up = (m - left) / (center - left)
    down = (right - m) / (right - center)
    banks = np.maximum(0.0, np.minimum(up, down))
    return np.pad(banks, ((0, 0), (0, 1))).astype(np.float32)


class Frontend(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("up", torch.from_numpy(lowpass_taps())[None, None, :])
        window = np.zeros(N_FFT)
        off = (N_FFT - WIN) // 2
        window[off:off + WIN] = np.hanning(WIN)  # == torch.hann_window(WIN, periodic=False), centred like torch.stft
        n = np.arange(N_FFT)
        k = np.arange(N_FFT // 2 + 1)[:, None]
        cos = (np.cos(2 * np.pi * k * n / N_FFT) * window).astype(np.float32)
        sin = (-np.sin(2 * np.pi * k * n / N_FFT) * window).astype(np.float32)
        self.register_buffer("dft", torch.from_numpy(np.concatenate([cos, sin]))[:, None, :])
        self.register_buffer("mel", torch.from_numpy(kaldi_mel_banks()))

    def upsample(self, wav: torch.Tensor) -> torch.Tensor:
        """(B, N) at 16 kHz -> (B, 2N) at 32 kHz."""
        pad = (UPSAMPLE_TAPS - 1) // 2
        y = F.conv_transpose1d(wav[:, None, :], self.up, stride=2, padding=pad, output_padding=1)
        return y[:, 0, :]

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        """(B, N) waveform at 16 kHz -> (B, 1, 128, T) normalised log mel."""
        x = self.upsample(wav)
        x = x[:, 1:] - 0.97 * x[:, :-1]  # pre-emphasis, same as conv1d with [-0.97, 1]
        x = F.pad(x[:, None, :], (N_FFT // 2, N_FFT // 2), mode="reflect")
        spec = F.conv1d(x, self.dft, stride=HOP)  # (B, 2*513, T)
        half = N_FFT // 2 + 1
        power = spec[:, :half] ** 2 + spec[:, half:] ** 2
        mel = torch.matmul(self.mel, power)
        return ((torch.log(mel + 1e-5) + 4.5) / 5.0)[:, None]


def reference_mel(wav32k: torch.Tensor) -> torch.Tensor:
    """EfficientAT AugmentMelSTFT in eval mode (torch.stft + torchaudio Kaldi banks). Used by the parity test only."""
    import torchaudio

    x = F.conv1d(wav32k[:, None, :], torch.tensor([[[-0.97, 1.0]]])).squeeze(1)
    x = torch.stft(x, N_FFT, hop_length=HOP, win_length=WIN, center=True, normalized=False,
                   window=torch.hann_window(WIN, periodic=False), return_complex=True)
    x = x.abs() ** 2
    banks, _ = torchaudio.compliance.kaldi.get_mel_banks(N_MELS, N_FFT, ENCODER_RATE, FMIN, FMAX, 100.0, -500.0, 1.0)
    banks = F.pad(banks, (0, 1))
    mel = torch.matmul(banks, x)
    return ((mel + 1e-5).log() + 4.5) / 5.0


class LowPass(nn.Module):
    """Fixed FIR low-pass at 16 kHz input (default cut-off 4 kHz). The reason model uses it so that every clip has
    the bandwidth of the 8 kHz training recordings, whatever the microphone gives."""

    def __init__(self, cutoff_hz: float = 4000.0, taps: int = 101):
        super().__init__()
        t = np.arange(taps) - (taps - 1) / 2
        fc = cutoff_hz / SAMPLE_RATE
        h = 2 * fc * np.sinc(2 * fc * t) * np.blackman(taps)
        self.register_buffer("h", torch.from_numpy((h / h.sum()).astype(np.float32))[None, None, :])
        self.pad = (taps - 1) // 2

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        return F.conv1d(wav[:, None, :], self.h, padding=self.pad)[:, 0, :]
