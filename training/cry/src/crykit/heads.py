"""Small heads on top of the encoder, and the full models that the export writes to ONNX."""

import torch
from torch import nn

from .encoder import EMB_DIM, Encoder
from .frontend import LowPass


class DetectorHead(nn.Module):
    """Frame embeddings (B, T, 960) -> frame probabilities (B, T, 2) for [cry, snore]. "Other" = neither."""

    def __init__(self, dim: int = EMB_DIM, hidden: int = 128, dropout: float = 0.3):
        super().__init__()
        self.proj = nn.Sequential(nn.LayerNorm(dim), nn.Linear(dim, hidden), nn.ReLU(), nn.Dropout(dropout))
        self.gru = nn.GRU(hidden, hidden // 2, batch_first=True, bidirectional=True)
        self.out = nn.Linear(hidden, 2)

    def forward(self, emb: torch.Tensor) -> torch.Tensor:
        h, _ = self.gru(self.proj(emb))
        return torch.sigmoid(self.out(h))


def clip_pool(p: torch.Tensor) -> torch.Tensor:
    """Linear-softmax pooling over time (B, T, C) -> (B, C), for clips with weak labels only."""
    return (p * p).sum(1) / p.sum(1).clamp_min(1e-7)


class ReasonHead(nn.Module):
    """Mean clip embedding (B, 960) -> class probabilities. One linear layer (multinomial logistic regression) with
    the standardisation in front; the calibration (temperature and class bias) is already folded into weight and bias."""

    def __init__(self, mean, scale, weight, bias):
        super().__init__()
        self.register_buffer("mean", torch.as_tensor(mean, dtype=torch.float32))
        self.register_buffer("scale", torch.as_tensor(scale, dtype=torch.float32))
        self.linear = nn.Linear(weight.shape[1], weight.shape[0])
        with torch.no_grad():
            self.linear.weight.copy_(torch.as_tensor(weight))
            self.linear.bias.copy_(torch.as_tensor(bias))

    def forward(self, clip_emb: torch.Tensor) -> torch.Tensor:
        z = self.linear((clip_emb - self.mean) / self.scale)
        return torch.softmax(z, dim=-1)


class DetectorModel(nn.Module):
    """wave (1, N) at 16 kHz -> frame_probs (T, 2)."""

    def __init__(self, encoder: Encoder, head: DetectorHead):
        super().__init__()
        self.encoder, self.head = encoder, head

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        return self.head(self.encoder(wav))[0]


class ReasonModel(nn.Module):
    """wave (1, N) at 16 kHz -> reason probabilities (K,)."""

    def __init__(self, encoder: Encoder, head: ReasonHead):
        super().__init__()
        self.lowpass, self.encoder, self.head = LowPass(), encoder, head

    def forward(self, wav: torch.Tensor) -> torch.Tensor:
        return self.head(reason_embedding(self.encoder, self.lowpass, wav))[0]


def reason_embedding(encoder: Encoder, lowpass: LowPass, wav: torch.Tensor) -> torch.Tensor:
    """The clip embedding the reason head sees: 4 kHz low-pass, encoder, mean over time."""
    return encoder(lowpass(wav)).mean(dim=1)
