"""Pretrained audio encoder: EfficientAT MobileNetV3 'mn10_as' (AudioSet, MIT licence).

wave (B, N) at 16 kHz -> frame embeddings (B, T, 960), one frame per 320 ms of 32 kHz audio (= 0.32 s).
"""

import torch
from torch import nn

from .efficientat.model import get_model
from .frontend import Frontend

ENCODER_NAME = "mn10_as"
EMB_DIM = 960
FRAME_SECONDS = 0.32  # 10 ms mel hop x time stride 32


class Encoder(nn.Module):
    def __init__(self, name: str = ENCODER_NAME):
        super().__init__()
        self.frontend = Frontend()
        width = {"mn04_as": 0.4, "mn05_as": 0.5, "mn10_as": 1.0}[name]
        mn = get_model(pretrained_name=name, width_mult=width, num_classes=527)
        self.features = mn.features
        self.dim = mn.features[-1].out_channels

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        x = self.features(self.frontend(wav))  # (B, C, F, T)
        return x.mean(dim=2).transpose(1, 2)  # (B, T, C)


def n_frames(n_samples: int) -> int:
    """Encoder frames for a 16 kHz input of n_samples (checked by tests against the real model)."""
    t = (2 * n_samples - 1) // 320 + 1  # mel frames: upsampled length minus 1 (pre-emphasis), centred STFT
    for _ in range(5):
        t = (t - 1) // 2 + 1
    return t
