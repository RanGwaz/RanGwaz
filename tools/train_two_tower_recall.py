#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Train and publish a versioned sequence-aware two-tower recall candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import torch
from torch import Tensor
from torch.utils.data import DataLoader, Dataset

try:
    from two_tower_retrieval import (
        DEFAULT_BEHAVIOR_TO_ID,
        TwoTowerConfig,
        TwoTowerModel,
        behavior_id,
    )
except ImportError:
    from tools.two_tower_retrieval import (
        DEFAULT_BEHAVIOR_TO_ID,
        TwoTowerConfig,
        TwoTowerModel,
        behavior_id,
    )

TOOLS_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get(
    "VIBELO_RECOMMENDATION_MODEL_DIR", TOOLS_DIR / "models" / "recommendation"
))
POSITIVE_TYPES = frozenset({"favorite", "like", "comment", "share", "click"})
VIEW_MIN_DURATION_MS = 3_000


@dataclass(frozen=True)
class BehaviorEvent:
    actor_key: str
    image_id: int
    behavior_type: str
    duration_ms: int
    occurred_at: datetime


@dataclass(frozen=True)
class MatureExposure:
    actor_key: str
    image_id: int
    occurred_at: datetime


@dataclass(frozen=True)
class TrainingExample:
    actor_key: str
    history: Tuple[BehaviorEvent, ...]
    target_image_id: int
    target_behavior: str
    target_at: datetime
    hard_negative_image_id: Optional[int] = None


@dataclass
class VectorStore:
    image_ids: Tensor
    vectors: Tensor
    index_by_id: Dict[int, int]

    @classmethod
    def from_rows(cls, rows: Iterable[Tuple[int, Sequence[float]]]) -> "VectorStore":
        unique: Dict[int, Tensor] = {}
        for image_id, value in rows:
            vector = torch.as_tensor(value, dtype=torch.float32).reshape(-1)
            if vector.numel() == 512 and bool(torch.isfinite(vector).all()):
                unique[int(image_id)] = vector
        if not unique:
            raise RuntimeError("No valid 512-dimensional SigLIP vectors were loaded")
        ids = sorted(unique)
        return cls(
            image_ids=torch.tensor(ids, dtype=torch.long),
            vectors=torch.stack([unique[item] for item in ids]).contiguous(),
            index_by_id={item: index for index, item in enumerate(ids)},
        )

    def __len__(self) -> int:
        return int(self.image_ids.numel())

    def contains(self, image_id: int) -> bool:
        return int(image_id) in self.index_by_id

    def get(self, image_id: int) -> Tensor:
        return self.vectors[self.index_by_id[int(image_id)]]


class ExampleDataset(Dataset):
    def __init__(self, examples: Sequence[TrainingExample]):
        self.examples = list(examples)

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> TrainingExample:
        return self.examples[index]


def normalize_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def actor_key(row: Mapping[str, Any]) -> str:
    if row.get("user_id") is not None:
        return f"u:{int(row['user_id'])}"
    visitor = str(row.get("visitor_id") or "").strip()
    return f"v:{visitor}" if visitor else ""


def is_positive(event: BehaviorEvent) -> bool:
    kind = event.behavior_type.lower()
    return kind in POSITIVE_TYPES or (
        kind == "view" and event.duration_ms >= VIEW_MIN_DURATION_MS
    )


def connect_mysql():
    try:
        import pymysql
    except ImportError as exc:
        raise SystemExit("Install tools/requirements_recommendation.txt") from exc
    return pymysql.connect(
        host=os.environ.get("VIBELO_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("VIBELO_DB_PORT", "3306")),
        user=os.environ.get("VIBELO_DB_USER", "rangwaz"),
        password=os.environ.get("VIBELO_DB_PASSWORD", "rangwaz123"),
        database=os.environ.get("VIBELO_DB_NAME", "rangwaz_image_dev"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=120,
    )


def load_behavior_events(days: int, limit: int) -> List[BehaviorEvent]:
    sql = """
      SELECT r.user_id,r.visitor_id,r.image_id,r.behavior_type,r.duration_ms,r.created_at
      FROM (
        SELECT ub.id,ub.user_id,ub.visitor_id,ub.image_id,
               LOWER(ub.behavior_type) behavior_type,
               COALESCE(ub.duration_ms,0) duration_ms,ub.created_at
        FROM user_behaviors ub
        JOIN images i ON i.id=ub.image_id AND i.status='PUBLISHED'
        WHERE ub.created_at>=DATE_SUB(NOW(),INTERVAL %s DAY)
          AND (ub.user_id IS NOT NULL OR NULLIF(ub.visitor_id,'') IS NOT NULL)
          AND LOWER(ub.behavior_type) IN
              ('favorite','like','comment','share','click','view','impression')
        ORDER BY ub.id DESC LIMIT %s
      ) r ORDER BY r.created_at,r.id
    """
    with connect_mysql() as connection, connection.cursor() as cursor:
        cursor.execute(sql, (int(days), int(limit)))
        rows = cursor.fetchall()
    return [
        BehaviorEvent(
            actor_key=actor_key(row),
            image_id=int(row["image_id"]),
            behavior_type=str(row["behavior_type"]).lower(),
            duration_ms=max(0, int(row.get("duration_ms") or 0)),
            occurred_at=normalize_datetime(row["created_at"]),
        )
        for row in rows if actor_key(row)
    ]


def load_mature_exposures(days: int, limit: int) -> List[MatureExposure]:
    sql = """
      SELECT r.user_id,r.visitor_id,r.image_id,r.exposed_at
      FROM (
        SELECT fi.id,fi.user_id,fi.visitor_id,fi.image_id,
               COALESCE(fi.occurred_at,fi.created_at) exposed_at
        FROM feed_impressions fi
        JOIN images i ON i.id=fi.image_id AND i.status='PUBLISHED'
        WHERE COALESCE(fi.occurred_at,fi.created_at)>=DATE_SUB(NOW(),INTERVAL %s DAY)
          AND COALESCE(fi.occurred_at,fi.created_at)<=DATE_SUB(NOW(),INTERVAL 24 HOUR)
          AND (fi.user_id IS NOT NULL OR NULLIF(fi.visitor_id,'') IS NOT NULL)
          AND NOT EXISTS (
            SELECT 1 FROM user_behaviors ub
            WHERE ub.image_id=fi.image_id
              AND ((fi.user_id IS NOT NULL AND ub.user_id=fi.user_id)
                OR (fi.user_id IS NULL AND ub.user_id IS NULL
                    AND ub.visitor_id=fi.visitor_id))
              AND ub.created_at>COALESCE(fi.occurred_at,fi.created_at)
              AND (LOWER(ub.behavior_type) IN
                    ('favorite','like','comment','share','click')
                OR (LOWER(ub.behavior_type)='view'
                    AND COALESCE(ub.duration_ms,0)>=%s))
          )
        ORDER BY fi.id DESC LIMIT %s
      ) r ORDER BY r.exposed_at,r.id
    """
    with connect_mysql() as connection, connection.cursor() as cursor:
        cursor.execute(sql, (int(days), VIEW_MIN_DURATION_MS, int(limit)))
        rows = cursor.fetchall()
    return [
        MatureExposure(
            actor_key=actor_key(row),
            image_id=int(row["image_id"]),
            occurred_at=normalize_datetime(row["exposed_at"]),
        )
        for row in rows if actor_key(row)
    ]


def build_next_positive_examples(
    events: Sequence[BehaviorEvent],
    exposures: Sequence[MatureExposure],
    min_history: int,
    max_history: int,
) -> List[TrainingExample]:
    """Create every chronological next-positive target for every actor."""

    by_actor: Dict[str, List[BehaviorEvent]] = {}
    hard_by_actor: Dict[str, List[MatureExposure]] = {}
    for event in events:
        by_actor.setdefault(event.actor_key, []).append(event)
    for exposure in exposures:
        hard_by_actor.setdefault(exposure.actor_key, []).append(exposure)
    result: List[TrainingExample] = []
    for key, values in by_actor.items():
        ordered = sorted(values, key=lambda item: item.occurred_at)
        hard_values = sorted(
            hard_by_actor.get(key, []), key=lambda item: item.occurred_at
        )
        seen_target_images: set[int] = set()
        for index, target in enumerate(ordered):
            if not is_positive(target):
                continue
            # One interaction chain (impression -> click -> like) must not turn
            # the same image into several targets or leak the answer into the
            # user tower. The first qualified positive owns the target label.
            if target.image_id in seen_target_images:
                continue
            seen_target_images.add(target.image_id)
            history = tuple(
                item for item in ordered[:index]
                if item.image_id != target.image_id
            )[-max_history:]
            if len(history) < min_history:
                continue
            excluded = {item.image_id for item in history}
            mature_at_target = target.occurred_at - timedelta(hours=24)
            candidates = [
                item for item in hard_values
                if item.occurred_at <= mature_at_target
                and item.image_id != target.image_id
                and item.image_id not in excluded
            ]
            result.append(TrainingExample(
                actor_key=key,
                history=history,
                target_image_id=target.image_id,
                target_behavior=target.behavior_type,
                target_at=target.occurred_at,
                hard_negative_image_id=candidates[-1].image_id if candidates else None,
            ))
    return sorted(result, key=lambda item: item.target_at)


def temporal_split(
    examples: Sequence[TrainingExample],
    train_ratio: float = 0.80,
    validation_ratio: float = 0.10,
) -> Tuple[List[TrainingExample], List[TrainingExample], List[TrainingExample]]:
    if not 0 < train_ratio < 1 or not 0 < validation_ratio < 1 - train_ratio:
        raise ValueError("Invalid temporal split ratios")
    ordered = sorted(examples, key=lambda item: item.target_at)
    train_end = math.floor(len(ordered) * train_ratio)
    validation_end = math.floor(len(ordered) * (train_ratio + validation_ratio))
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]


def load_all_siglip_vectors() -> VectorStore:
    try:
        from pymilvus import Collection, connections, utility
    except ImportError as exc:
        raise SystemExit("Install tools/requirements_recommendation.txt") from exc
    collection_name = os.environ.get(
        "VIBELO_MILVUS_COLLECTION",
        "vibelo_image_vectors_siglip2_base_p224_d512",
    )
    alias = f"two_tower_train_{os.getpid()}"
    connections.connect(
        alias=alias,
        host=os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1"),
        port=os.environ.get("VIBELO_MILVUS_PORT", "19530"),
    )
    try:
        if not utility.has_collection(collection_name, using=alias):
            raise SystemExit(f"Milvus collection not found: {collection_name}")
        collection = Collection(collection_name, using=alias)
        collection.load()
        published_ids: set[int] = set()
        with connect_mysql() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id FROM images WHERE status='PUBLISHED'")
            while True:
                published_batch = cursor.fetchmany(4096)
                if not published_batch:
                    break
                published_ids.update(int(row["id"]) for row in published_batch)
        if not published_ids:
            raise SystemExit("No published images are available for two-tower training")

        # Preallocate once instead of retaining the full catalog as Python
        # lists before copying it into Torch. Also exclude stale unpublished
        # vectors from offline retrieval metrics.
        image_ids = torch.empty(len(published_ids), dtype=torch.long)
        vectors = torch.empty((len(published_ids), 512), dtype=torch.float32)
        index_by_id: Dict[int, int] = {}
        write_index = 0
        iterator = collection.query_iterator(
            batch_size=2048,
            expr="image_id > 0",
            output_fields=["image_id", "embedding"],
        )
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                for row in batch:
                    image_id = int(row.get("image_id") or 0)
                    value = row.get("embedding")
                    if (
                        image_id not in published_ids
                        or image_id in index_by_id
                        or value is None
                    ):
                        continue
                    vector = torch.as_tensor(value, dtype=torch.float32).reshape(-1)
                    if vector.numel() != 512 or not bool(torch.isfinite(vector).all()):
                        continue
                    image_ids[write_index] = image_id
                    vectors[write_index].copy_(vector)
                    index_by_id[image_id] = write_index
                    write_index += 1
        finally:
            iterator.close()
        if write_index == 0:
            raise RuntimeError("No published 512-dimensional SigLIP vectors were loaded")
        return VectorStore(
            image_ids=image_ids[:write_index],
            vectors=vectors[:write_index],
            index_by_id=index_by_id,
        )
    finally:
        connections.disconnect(alias)


def filter_vectorized_examples(
    examples: Sequence[TrainingExample],
    vectors: VectorStore,
    min_history: int,
    max_history: int,
) -> List[TrainingExample]:
    result = []
    for example in examples:
        if not vectors.contains(example.target_image_id):
            continue
        history = tuple(
            item for item in example.history if vectors.contains(item.image_id)
        )[-max_history:]
        if len(history) < min_history:
            continue
        hard_id = example.hard_negative_image_id
        if hard_id is not None and not vectors.contains(hard_id):
            hard_id = None
        result.append(replace(
            example, history=history, hard_negative_image_id=hard_id
        ))
    return result


def collate_examples(
    examples: Sequence[TrainingExample],
    vectors: VectorStore,
    config: TwoTowerConfig,
) -> Dict[str, Any]:
    size, length = len(examples), config.max_sequence_length
    histories = torch.zeros(size, length, 512)
    behaviors = torch.zeros(size, length, dtype=torch.long)
    ages = torch.zeros(size, length)
    durations = torch.zeros(size, length)
    mask = torch.zeros(size, length, dtype=torch.bool)
    targets = torch.zeros(size, 512)
    target_ids = torch.zeros(size, dtype=torch.long)
    hard = torch.zeros(size, 1, 512)
    hard_mask = torch.zeros(size, 1, dtype=torch.bool)
    excluded_ids: List[List[int]] = []
    for row, example in enumerate(examples):
        # Public train/serve contract: index zero is newest.
        selected = list(reversed(example.history[-length:]))
        excluded_ids.append([item.image_id for item in selected])
        for column, event in enumerate(selected):
            histories[row, column] = vectors.get(event.image_id)
            behaviors[row, column] = behavior_id(event.behavior_type)
            ages[row, column] = max(
                0.0, (example.target_at - event.occurred_at).total_seconds() / 3600
            )
            durations[row, column] = max(0, event.duration_ms)
            mask[row, column] = True
        targets[row] = vectors.get(example.target_image_id)
        target_ids[row] = example.target_image_id
        if example.hard_negative_image_id is not None:
            hard[row, 0] = vectors.get(example.hard_negative_image_id)
            hard_mask[row, 0] = True
    return {
        "history_vectors": histories,
        "behavior_ids": behaviors,
        "age_hours": ages,
        "duration_ms": durations,
        "attention_mask": mask,
        "target_vectors": targets,
        "target_ids": target_ids,
        "hard_negative_vectors": hard,
        "hard_negative_mask": hard_mask,
        "excluded_ids": excluded_ids,
    }


def make_loader(
    examples: Sequence[TrainingExample],
    vectors: VectorStore,
    config: TwoTowerConfig,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> DataLoader:
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(
        ExampleDataset(examples),
        batch_size=min(batch_size, len(examples)),
        shuffle=shuffle,
        num_workers=0,
        generator=generator,
        collate_fn=lambda items: collate_examples(items, vectors, config),
    )


def to_device(batch: Mapping[str, Any], device: torch.device) -> Dict[str, Any]:
    return {
        key: value.to(device, non_blocking=device.type == "cuda")
        if torch.is_tensor(value) else value
        for key, value in batch.items()
    }


def batch_loss(model: TwoTowerModel, batch: Mapping[str, Any]) -> Tensor:
    return model.contrastive_loss(
        batch["history_vectors"], batch["behavior_ids"], batch["age_hours"],
        batch["duration_ms"], batch["attention_mask"], batch["target_vectors"],
        batch["target_ids"], batch["hard_negative_vectors"],
        batch["hard_negative_mask"],
    )


@torch.no_grad()
def evaluate_loss(model: TwoTowerModel, loader: DataLoader, device: torch.device) -> float:
    model.eval()
    losses = []
    for raw in loader:
        if raw["target_ids"].numel() < 2:
            continue
        losses.append(float(batch_loss(model, to_device(raw, device)).item()))
    return sum(losses) / len(losses) if losses else math.inf


def train_model(
    model: TwoTowerModel,
    train_loader: DataLoader,
    validation_loader: DataLoader,
    device: torch.device,
    epochs: int,
    patience: int,
    learning_rate: float,
    weight_decay: float,
    amp_enabled: bool,
) -> Tuple[TwoTowerModel, Dict[str, Any]]:
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay
    )
    try:
        scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled)
    except (AttributeError, TypeError):
        # Compatibility with the oldest supported PyTorch 2.2 builds.
        scaler = torch.cuda.amp.GradScaler(enabled=amp_enabled)
    best_loss, best_epoch, stale = math.inf, 0, 0
    best_state: Optional[Dict[str, Tensor]] = None
    history = []
    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for raw in train_loader:
            if raw["target_ids"].numel() < 2:
                continue
            batch = to_device(raw, device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type=device.type, dtype=torch.float16, enabled=amp_enabled
            ):
                loss = batch_loss(model, batch)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().item()))
        if not losses:
            raise RuntimeError("No trainable batch with at least two samples")
        validation_loss = evaluate_loss(model, validation_loader, device)
        epoch_result = {
            "epoch": epoch,
            "train_loss": sum(losses) / len(losses),
            "validation_loss": validation_loss,
        }
        history.append(epoch_result)
        print(json.dumps(epoch_result), flush=True)
        if validation_loss < best_loss - 1e-4:
            best_loss, best_epoch, stale = validation_loss, epoch, 0
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("Validation never produced a finite loss")
    model.load_state_dict(best_state)
    model.to(device).eval()
    return model, {
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "epochs_completed": len(history),
        "early_stopped": len(history) < epochs,
        "history": history,
    }


@torch.no_grad()
def evaluate_retrieval(
    model: TwoTowerModel,
    loader: DataLoader,
    vectors: VectorStore,
    device: torch.device,
) -> Dict[str, float]:
    model.eval()
    encoded_chunks = []
    for start in range(0, len(vectors), 2048):
        raw = vectors.vectors[start:start + 2048].to(device)
        encoded_chunks.append(model.encode_item(raw).cpu())
    catalog = torch.cat(encoded_chunks)
    index_by_id = vectors.index_by_id
    ranks: List[int] = []
    for raw in loader:
        batch = to_device(raw, device)
        users = model.encode_user(
            batch["history_vectors"], batch["behavior_ids"], batch["age_hours"],
            batch["duration_ms"], batch["attention_mask"],
        ).cpu()
        scores = users @ catalog.transpose(0, 1)
        for row, target_id in enumerate(raw["target_ids"].tolist()):
            target_index = index_by_id[int(target_id)]
            for image_id in raw["excluded_ids"][row]:
                index = index_by_id.get(int(image_id))
                if index is not None and index != target_index:
                    scores[row, index] = -torch.inf
            target_score = scores[row, target_index]
            ranks.append(1 + int(torch.sum(scores[row] > target_score).item()))
    if not ranks:
        raise RuntimeError("No evaluation examples")
    rank_tensor = torch.tensor(ranks, dtype=torch.float32)
    return {
        "example_count": float(len(ranks)),
        "recall@10": float((rank_tensor <= 10).float().mean()),
        "recall@50": float((rank_tensor <= 50).float().mean()),
        "mrr": float((1.0 / rank_tensor).mean()),
    }


def synthetic_dataset(seed: int, count: int, max_history: int) -> Tuple[List[TrainingExample], VectorStore]:
    generator = torch.Generator().manual_seed(seed)
    randomizer = random.Random(seed)
    centers = torch.randn(8, 512, generator=generator)
    centers = torch.nn.functional.normalize(centers, dim=1)
    rows = []
    for image_id in range(1, 129):
        center = centers[(image_id - 1) % 8]
        vector = center + 0.08 * torch.randn(512, generator=generator)
        rows.append((image_id, vector.tolist()))
    vectors = VectorStore.from_rows(rows)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    examples: List[TrainingExample] = []
    actors = max(12, count // 6)
    for actor in range(actors):
        cluster = actor % 8
        events = []
        for step in range(10):
            image_id = 1 + cluster + 8 * randomizer.randrange(16)
            events.append(BehaviorEvent(
                actor_key=f"synthetic:{actor}", image_id=image_id,
                behavior_type=("view", "click", "like")[step % 3],
                duration_ms=5_000, occurred_at=base + timedelta(hours=actor * 12 + step),
            ))
        hard_id = 1 + ((cluster + 3) % 8)
        for target_index in range(2, len(events)):
            examples.append(TrainingExample(
                actor_key=f"synthetic:{actor}",
                history=tuple(events[max(0, target_index - max_history):target_index]),
                target_image_id=events[target_index].image_id,
                target_behavior=events[target_index].behavior_type,
                target_at=events[target_index].occurred_at,
                hard_negative_image_id=hard_id,
            ))
    return sorted(examples, key=lambda item: item.target_at)[:count], vectors


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def resolve_device(value: str) -> torch.device:
    device = torch.device(
        "cuda" if value == "auto" and torch.cuda.is_available()
        else "cpu" if value == "auto" else value
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is unavailable")
    return device


def fail_gate(message: str) -> None:
    raise SystemExit(f"Training gate rejected candidate: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> Dict[str, Any]:
    set_seed(args.seed)
    mode = "synthetic_smoke" if args.synthetic_smoke else "behavior"
    if args.synthetic_smoke:
        examples, vectors = synthetic_dataset(
            args.seed, args.synthetic_examples, args.max_history
        )
    else:
        examples = build_next_positive_examples(
            load_behavior_events(args.days, args.limit),
            load_mature_exposures(args.days, args.limit),
            args.min_history, args.max_history,
        )
        actor_count = len({item.actor_key for item in examples})
        if actor_count < args.min_actors:
            fail_gate(f"only {actor_count} positive actors; need {args.min_actors}")
        if len(examples) < args.min_examples:
            fail_gate(f"only {len(examples)} examples; need {args.min_examples}")
        vectors = load_all_siglip_vectors()
        examples = filter_vectorized_examples(
            examples, vectors, args.min_history, args.max_history
        )
        actor_count = len({item.actor_key for item in examples})
        if actor_count < args.min_actors:
            fail_gate(f"only {actor_count} vectorized actors; need {args.min_actors}")
        if len(examples) < args.min_examples:
            fail_gate(f"only {len(examples)} vectorized examples; need {args.min_examples}")

    actor_count = len({item.actor_key for item in examples})
    train_set, validation_set, test_set = temporal_split(examples)
    if min(len(train_set), len(validation_set), len(test_set)) < 2:
        fail_gate("each temporal split must contain at least two examples")
    config = TwoTowerConfig(
        max_sequence_length=args.max_history,
        transformer_layers=1 if args.synthetic_smoke else args.transformer_layers,
        transformer_heads=args.transformer_heads,
        transformer_feedforward_dim=256 if args.synthetic_smoke
        else args.transformer_feedforward_dim,
        dropout=args.dropout,
        temperature=args.temperature,
    )
    device = resolve_device(args.device)
    amp_enabled = device.type == "cuda" and not args.no_amp
    batch_size = min(args.batch_size, len(train_set))
    train_loader = make_loader(
        train_set, vectors, config, batch_size, True, args.seed
    )
    validation_loader = make_loader(
        validation_set, vectors, config, batch_size, False, args.seed
    )
    test_loader = make_loader(
        test_set, vectors, config, batch_size, False, args.seed
    )
    model = TwoTowerModel(config).to(device)
    started = time.monotonic()
    epoch_limit = min(args.epochs, 4) if args.synthetic_smoke else args.epochs
    model, training_result = train_model(
        model, train_loader, validation_loader, device, epoch_limit,
        args.patience, args.learning_rate, args.weight_decay, amp_enabled,
    )
    validation_metrics = evaluate_retrieval(
        model, validation_loader, vectors, device
    )
    test_metrics = evaluate_retrieval(model, test_loader, vectors, device)
    elapsed = time.monotonic() - started
    gate_thresholds = {
        "validation_recall@50": float(args.min_validation_recall_at_50),
        "test_recall@50": float(args.min_test_recall_at_50),
    }
    gate_values = {
        "validation_recall@50": float(validation_metrics["recall@50"]),
        "test_recall@50": float(test_metrics["recall@50"]),
    }
    gate_failures = [
        f"{name}={value:.6f} is below {gate_thresholds[name]:.6f}"
        for name, value in gate_values.items()
        if not math.isfinite(value) or value < gate_thresholds[name]
    ]
    if args.synthetic_smoke:
        gate_failures.append("synthetic artifacts are never publishable")
    gates_passed = not gate_failures


    if args.output_dir:
        output_root = Path(args.output_dir).resolve()
    elif args.synthetic_smoke:
        output_root = Path(tempfile.mkdtemp(prefix="vibelo-two-tower-smoke-"))
    else:
        output_root = MODEL_DIR.resolve()
    version = args.version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version_dir = output_root / "two_tower" / "versions" / version
    if version_dir.exists():
        fail_gate(f"version already exists: {version_dir}")
    version_dir.mkdir(parents=True)
    checkpoint_path = version_dir / "model.pt"
    metadata = {
        **training_result,
        "mode": mode,
        "actor_count": actor_count,
        "sample_count": len(examples),
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "elapsed_seconds": elapsed,
    }
    payload = {
        "format_version": "1",
        "model_name": "vibelo-two-tower-recall",
        "version": version,
        "config": config.to_dict(),
        "behavior_to_id": dict(DEFAULT_BEHAVIOR_TO_ID),
        "model_state_dict": {
            key: value.detach().cpu() for key, value in model.state_dict().items()
        },
        "training_metadata": metadata,
    }
    temporary_checkpoint = checkpoint_path.with_suffix(".pt.tmp")
    torch.save(payload, temporary_checkpoint)
    os.replace(temporary_checkpoint, checkpoint_path)
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "model_name": "vibelo-two-tower-recall",
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_path": str(checkpoint_path.resolve()),
        "sha256": sha256_file(checkpoint_path),
        "config": config.to_dict(),
        "behavior_to_id": dict(DEFAULT_BEHAVIOR_TO_ID),
        "data": {
            "mode": mode,
            "actor_count": actor_count,
            "sample_count": len(examples),
            "train_count": len(train_set),
            "validation_count": len(validation_set),
            "test_count": len(test_set),
            "candidate_vector_count": len(vectors),
            "split": "global_chronological_80_10_10",
        },
        "metrics": {"validation": validation_metrics, "test": test_metrics},
        "training": {
            **training_result,
            "gatesPassed": gates_passed,
            "gateThresholds": gate_thresholds,
            "gateValues": gate_values,
            "gateFailures": gate_failures,
            "device": str(device),
            "amp": amp_enabled,
            "seed": args.seed,
            "elapsed_seconds": elapsed,
        },
    }
    write_json(version_dir / "manifest.json", manifest)
    if gates_passed:
        try:
            from two_tower_registry import register_candidate
        except ImportError:
            from tools.two_tower_registry import register_candidate
        register_candidate(manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-smoke", action="store_true")
    parser.add_argument("--synthetic-examples", type=int, default=96)
    parser.add_argument("--output-dir")
    parser.add_argument("--version")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--limit", type=int, default=2_000_000)
    parser.add_argument("--min-actors", type=int, default=50)
    parser.add_argument("--min-examples", type=int, default=500)
    parser.add_argument("--min-history", type=int, default=2)
    parser.add_argument("--max-history", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--transformer-layers", type=int, default=2)
    parser.add_argument("--transformer-heads", type=int, default=8)
    parser.add_argument("--transformer-feedforward-dim", type=int, default=768)
    parser.add_argument("--dropout", type=float, default=0.10)
    parser.add_argument("--temperature", type=float, default=0.07)
    parser.add_argument("--min-validation-recall-at-50", type=float, default=0.01)
    parser.add_argument("--min-test-recall-at-50", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--no-amp", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.min_history < 1 or args.max_history < args.min_history:
        raise SystemExit("Require 1 <= min-history <= max-history")
    if args.batch_size < 2:
        raise SystemExit("--batch-size must be at least 2")
    if args.synthetic_examples < 20:
        raise SystemExit("--synthetic-examples must be at least 20")
    if not 0.0 <= args.min_validation_recall_at_50 <= 1.0 \
            or not 0.0 <= args.min_test_recall_at_50 <= 1.0:
        raise SystemExit("Recall@50 gate thresholds must be in [0, 1]")
    manifest = run(args)
    if not args.synthetic_smoke and not manifest["training"]["gatesPassed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
