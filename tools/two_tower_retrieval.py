#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Trainable two-tower retrieval model shared by training and serving.

The item tower consumes existing 512-dimensional SigLIP image vectors. The
user tower reuses the same item projection for the chronological history and
combines behavior, recency and dwell time with a Transformer and attention
pooling. Both towers return unit-normalized 256-dimensional vectors. Sequence
index zero is the newest event in training and serving.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import torch
from torch import Tensor, nn
from torch.nn import functional as F


DEFAULT_BEHAVIOR_TO_ID: Dict[str, int] = {
    "padding": 0,
    "unknown": 1,
    "impression": 2,
    "view": 3,
    "click": 4,
    "like": 5,
    "favorite": 6,
    "comment": 7,
    "share": 8,
}


def behavior_id(name: Optional[str], mapping: Optional[Mapping[str, int]] = None) -> int:
    values = mapping or DEFAULT_BEHAVIOR_TO_ID
    normalized = str(name or "unknown").strip().lower()
    return int(values.get(normalized, values.get("unknown", 1)))


@dataclass(frozen=True)
class TwoTowerConfig:
    """Serializable architecture configuration with a fixed vector contract."""

    input_dim: int = 512
    embedding_dim: int = 256
    behavior_vocab_size: int = 9
    max_sequence_length: int = 64
    transformer_layers: int = 2
    transformer_heads: int = 8
    transformer_feedforward_dim: int = 768
    dropout: float = 0.10
    temperature: float = 0.07

    def __post_init__(self) -> None:
        if self.input_dim != 512:
            raise ValueError("input_dim must remain 512 for SigLIP vectors")
        if self.embedding_dim != 256:
            raise ValueError("embedding_dim must remain 256 for the retrieval index")
        if self.behavior_vocab_size < 2:
            raise ValueError("behavior_vocab_size must include padding and unknown")
        if self.max_sequence_length < 1:
            raise ValueError("max_sequence_length must be positive")
        if self.transformer_layers < 1:
            raise ValueError("transformer_layers must be positive")
        if self.transformer_heads < 1 or self.embedding_dim % self.transformer_heads != 0:
            raise ValueError("transformer_heads must divide embedding_dim")
        if self.transformer_feedforward_dim < self.embedding_dim:
            raise ValueError("transformer_feedforward_dim must be >= embedding_dim")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.temperature <= 0.0:
            raise ValueError("temperature must be positive")

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "TwoTowerConfig":
        valid_names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in dict(values).items() if key in valid_names})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TwoTowerModel(nn.Module):
    """Sequence-aware user tower plus a shared SigLIP item projection."""

    def __init__(self, config: TwoTowerConfig):
        super().__init__()
        self.config = config
        dimension = config.embedding_dim
        self.item_projection = nn.Sequential(
            nn.Linear(config.input_dim, dimension),
            nn.GELU(),
            nn.LayerNorm(dimension),
            nn.Linear(dimension, dimension),
        )
        self.behavior_embedding = nn.Embedding(
            config.behavior_vocab_size, dimension, padding_idx=0
        )
        self.context_projection = nn.Sequential(
            nn.Linear(2, dimension),
            nn.GELU(),
            nn.Linear(dimension, dimension),
        )
        self.position_embedding = nn.Embedding(config.max_sequence_length, dimension)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=dimension,
            nhead=config.transformer_heads,
            dim_feedforward=config.transformer_feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.sequence_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=config.transformer_layers,
            norm=nn.LayerNorm(dimension),
            enable_nested_tensor=False,
        )
        self.attention_pool = nn.Sequential(
            nn.Linear(dimension, dimension),
            nn.Tanh(),
            nn.Linear(dimension, 1, bias=False),
        )
        self.user_projection = nn.Sequential(
            nn.Linear(dimension, dimension),
            nn.GELU(),
            nn.LayerNorm(dimension),
            nn.Linear(dimension, dimension),
        )

    def encode_item(self, item_vectors: Tensor) -> Tensor:
        """Project SigLIP vectors ending in 512 to normalized vectors ending in 256."""

        if item_vectors.ndim < 2 or item_vectors.shape[-1] != self.config.input_dim:
            raise ValueError(
                f"item_vectors must end with {self.config.input_dim}; "
                f"received {tuple(item_vectors.shape)}"
            )
        projected = self.item_projection(item_vectors.float())
        return F.normalize(projected, p=2, dim=-1, eps=1e-8)

    def encode_user(
        self,
        history_vectors: Tensor,
        behavior_ids: Tensor,
        age_hours: Tensor,
        duration_ms: Tensor,
        attention_mask: Tensor,
    ) -> Tensor:
        """Encode newest-first padded sequences; True attention entries are valid."""

        if history_vectors.ndim != 3 or history_vectors.shape[-1] != self.config.input_dim:
            raise ValueError(
                f"history_vectors must be [B,L,{self.config.input_dim}]; "
                f"received {tuple(history_vectors.shape)}"
            )
        batch_size, sequence_length, _ = history_vectors.shape
        expected = (batch_size, sequence_length)
        for name, value in (
            ("behavior_ids", behavior_ids),
            ("age_hours", age_hours),
            ("duration_ms", duration_ms),
            ("attention_mask", attention_mask),
        ):
            if tuple(value.shape) != expected:
                raise ValueError(f"{name} must be {expected}; received {tuple(value.shape)}")
        if sequence_length > self.config.max_sequence_length:
            raise ValueError(
                f"sequence length {sequence_length} exceeds "
                f"max_sequence_length {self.config.max_sequence_length}"
            )
        valid_mask = attention_mask.to(device=history_vectors.device, dtype=torch.bool)
        if not bool(valid_mask.any(dim=1).all()):
            raise ValueError("each user sequence must contain at least one valid event")

        item_tokens = self.encode_item(history_vectors)
        behavior_tokens = self.behavior_embedding(behavior_ids.long())
        age_feature = torch.log1p(
            age_hours.float().clamp(min=0.0, max=24.0 * 365.0)
        ) / 10.0
        duration_feature = torch.log1p(
            duration_ms.float().clamp(min=0.0, max=600_000.0)
        ) / 10.0
        context_tokens = self.context_projection(
            torch.stack((age_feature, duration_feature), dim=-1)
        )
        positions = torch.arange(sequence_length, device=history_vectors.device)
        position_tokens = self.position_embedding(positions).unsqueeze(0)
        tokens = item_tokens + behavior_tokens + context_tokens + position_tokens
        tokens = tokens.masked_fill(~valid_mask.unsqueeze(-1), 0.0)
        encoded = self.sequence_encoder(tokens, src_key_padding_mask=~valid_mask)
        attention_logits = self.attention_pool(encoded).squeeze(-1)
        attention_logits = attention_logits.masked_fill(
            ~valid_mask, torch.finfo(encoded.dtype).min
        )
        attention_weights = torch.softmax(attention_logits, dim=1)
        pooled = torch.sum(encoded * attention_weights.unsqueeze(-1), dim=1)
        return F.normalize(self.user_projection(pooled), p=2, dim=-1, eps=1e-8)

    def contrastive_loss(
        self,
        history_vectors: Tensor,
        behavior_ids: Tensor,
        age_hours: Tensor,
        duration_ms: Tensor,
        attention_mask: Tensor,
        target_vectors: Tensor,
        target_ids: Tensor,
        hard_negative_vectors: Optional[Tensor] = None,
        hard_negative_mask: Optional[Tensor] = None,
    ) -> Tensor:
        """Duplicate-safe in-batch InfoNCE with optional sample-local negatives."""

        user_embeddings = self.encode_user(
            history_vectors, behavior_ids, age_hours, duration_ms, attention_mask
        )
        target_embeddings = self.encode_item(target_vectors)
        hard_embeddings = None
        if hard_negative_vectors is not None:
            if hard_negative_vectors.ndim == 2:
                hard_negative_vectors = hard_negative_vectors.unsqueeze(1)
            if hard_negative_vectors.ndim != 3:
                raise ValueError("hard negatives must be [B,512] or [B,H,512]")
            hard_embeddings = self.encode_item(hard_negative_vectors)
        return duplicate_safe_info_nce(
            user_embeddings,
            target_embeddings,
            target_ids,
            self.config.temperature,
            hard_embeddings,
            hard_negative_mask,
        )


def duplicate_safe_info_nce(
    user_embeddings: Tensor,
    target_embeddings: Tensor,
    target_ids: Tensor,
    temperature: float,
    hard_negative_embeddings: Optional[Tensor] = None,
    hard_negative_mask: Optional[Tensor] = None,
) -> Tensor:
    """Symmetric in-batch InfoNCE masking duplicate-target false negatives."""

    if user_embeddings.ndim != 2 or target_embeddings.ndim != 2:
        raise ValueError("user_embeddings and target_embeddings must be rank-2")
    if user_embeddings.shape != target_embeddings.shape:
        raise ValueError("user and target embeddings must have identical shapes")
    batch_size = user_embeddings.shape[0]
    if target_ids.numel() != batch_size:
        raise ValueError("target_ids must contain one id per sample")
    if batch_size < 2:
        raise ValueError("InfoNCE requires at least two samples")

    users = F.normalize(user_embeddings.float(), dim=-1, eps=1e-8)
    targets = F.normalize(target_embeddings.float(), dim=-1, eps=1e-8)
    logits = users @ targets.transpose(0, 1) / float(temperature)
    ids = target_ids.reshape(-1).to(logits.device)
    same_target = ids[:, None].eq(ids[None, :])
    diagonal = torch.eye(batch_size, device=logits.device, dtype=torch.bool)
    logits = logits.masked_fill(
        same_target & ~diagonal, torch.finfo(logits.dtype).min
    )

    if hard_negative_embeddings is not None:
        if hard_negative_embeddings.ndim == 2:
            hard_negative_embeddings = hard_negative_embeddings.unsqueeze(1)
        if (
            hard_negative_embeddings.ndim != 3
            or hard_negative_embeddings.shape[0] != batch_size
        ):
            raise ValueError("hard_negative_embeddings must be [B,H,D]")
        hard = F.normalize(hard_negative_embeddings.float(), dim=-1, eps=1e-8)
        hard_logits = torch.einsum("bd,bhd->bh", users, hard) / float(temperature)
        if hard_negative_mask is not None:
            mask = hard_negative_mask.to(device=logits.device, dtype=torch.bool)
            if mask.ndim == 1:
                mask = mask.unsqueeze(1)
            if mask.shape != hard_logits.shape:
                raise ValueError("hard_negative_mask must match [B,H]")
            hard_logits = hard_logits.masked_fill(
                ~mask, torch.finfo(logits.dtype).min
            )
        logits = torch.cat((logits, hard_logits), dim=1)

    labels = torch.arange(batch_size, device=logits.device)
    user_to_item = F.cross_entropy(logits, labels)
    reverse_logits = targets @ users.transpose(0, 1) / float(temperature)
    log_denominator = torch.logsumexp(reverse_logits, dim=1)
    positive_logits = reverse_logits.masked_fill(
        ~same_target, torch.finfo(reverse_logits.dtype).min
    )
    log_numerator = torch.logsumexp(positive_logits, dim=1)
    item_to_user = (log_denominator - log_numerator).mean()
    return 0.5 * (user_to_item + item_to_user)


def load_two_tower_checkpoint(
    path: Union[str, Path],
    device: Union[str, torch.device] = "cpu",
) -> Tuple[TwoTowerModel, Dict[str, Any]]:
    """Load a checkpoint and return the evaluation model and raw payload."""

    checkpoint_path = Path(path)
    try:
        payload = torch.load(checkpoint_path, map_location=device, weights_only=True)
    except TypeError:
        payload = torch.load(checkpoint_path, map_location=device)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid checkpoint payload: {checkpoint_path}")
    config_payload = payload.get("config")
    state_dict = payload.get("model_state_dict")
    if not isinstance(config_payload, Mapping) or not isinstance(state_dict, Mapping):
        raise ValueError("checkpoint must contain config and model_state_dict")
    model = TwoTowerModel(TwoTowerConfig.from_dict(config_payload))
    model.load_state_dict(state_dict, strict=True)
    model.to(device)
    model.eval()
    return model, dict(payload)


__all__ = [
    "DEFAULT_BEHAVIOR_TO_ID",
    "TwoTowerConfig",
    "TwoTowerModel",
    "behavior_id",
    "duplicate_safe_info_nce",
    "load_two_tower_checkpoint",
]
