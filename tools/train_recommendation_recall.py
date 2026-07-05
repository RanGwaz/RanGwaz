#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Train Vibelo sequence-aware recall weights from real behavior logs.

The online recall service already uses image vectors. This script trains the
lightweight user-tower part: behavior weights, time decay, and duration boost
used to combine a user's recent interacted image vectors into one interest
vector.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pymysql

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models" / "recommendation"
RECALL_METADATA_PATH = MODEL_DIR / "recall_metadata.json"

MILVUS_HOST = os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("VIBELO_MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("VIBELO_MILVUS_COLLECTION", "vibelo_image_vectors_siglip2_base_p224_d512")
VECTOR_FIELD = "embedding"

DEFAULT_BEHAVIOR_WEIGHTS = {
    "favorite": 5.0,
    "like": 4.0,
    "comment": 4.0,
    "share": 4.0,
    "click": 2.5,
    "view": 1.8,
    "impression": 0.35,
}
TARGET_BEHAVIORS = {"favorite", "like", "comment", "share", "click", "view"}
ALL_BEHAVIORS = tuple(DEFAULT_BEHAVIOR_WEIGHTS.keys())


@dataclass(frozen=True)
class BehaviorEvent:
    actor_key: str
    image_id: int
    behavior_type: str
    duration_ms: int
    age_hours: int
    created_at: Any


@dataclass(frozen=True)
class TrainingExample:
    actor_key: str
    history: Tuple[BehaviorEvent, ...]
    target_image_id: int
    target_behavior: str


def connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("VIBELO_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("VIBELO_DB_PORT", "3306")),
        user=os.environ.get("VIBELO_DB_USER", "rangwaz"),
        password=os.environ.get("VIBELO_DB_PASSWORD", "rangwaz123"),
        database=os.environ.get("VIBELO_DB_NAME", "rangwaz_image_dev"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def clamp(value: float, low: float, high: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return low
    return min(high, max(low, float(value)))


def actor_key(row: Dict[str, Any]) -> str:
    user_id = row.get("user_id")
    visitor_id = str(row.get("visitor_id") or "").strip()
    if user_id is not None:
        return f"u:{int(user_id)}"
    return f"v:{visitor_id}"


def load_behavior_events(days: int, limit: int) -> List[BehaviorEvent]:
    sql = """
        SELECT
          recent.user_id,
          recent.visitor_id,
          recent.image_id,
          recent.behavior_type,
          recent.duration_ms,
          recent.age_hours,
          recent.created_at
        FROM (
          SELECT
            ub.id,
            ub.user_id,
            ub.visitor_id,
            ub.image_id,
            ub.behavior_type,
            COALESCE(ub.duration_ms,0) AS duration_ms,
            TIMESTAMPDIFF(HOUR,ub.created_at,NOW()) AS age_hours,
            ub.created_at
          FROM user_behaviors ub
          JOIN images i ON i.id=ub.image_id AND i.status='PUBLISHED'
          WHERE ub.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            AND (ub.user_id IS NOT NULL OR ub.visitor_id IS NOT NULL)
            AND ub.behavior_type IN ('favorite','like','comment','share','click','view','impression')
          ORDER BY ub.id DESC
          LIMIT %s
        ) recent
        ORDER BY COALESCE(CONCAT('u:',recent.user_id), CONCAT('v:',recent.visitor_id)), recent.created_at, recent.id
    """
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (days, limit))
            rows = cursor.fetchall()
    events: List[BehaviorEvent] = []
    for row in rows:
        key = actor_key(row)
        if key == "v:":
            continue
        events.append(BehaviorEvent(
            actor_key=key,
            image_id=int(row["image_id"]),
            behavior_type=str(row.get("behavior_type") or "unknown").lower(),
            duration_ms=int(row.get("duration_ms") or 0),
            age_hours=max(0, int(row.get("age_hours") or 0)),
            created_at=row.get("created_at"),
        ))
    return events


def build_examples(events: Sequence[BehaviorEvent], min_history: int, max_history: int) -> List[TrainingExample]:
    by_actor: Dict[str, List[BehaviorEvent]] = {}
    for event in events:
        by_actor.setdefault(event.actor_key, []).append(event)
    examples: List[TrainingExample] = []
    for key, actor_events in by_actor.items():
        positives = [index for index, event in enumerate(actor_events) if event.behavior_type in TARGET_BEHAVIORS]
        if len(positives) < 2:
            continue
        target_index = positives[-1]
        history = tuple(actor_events[max(0, target_index - max_history):target_index])
        target = actor_events[target_index]
        if len(history) < min_history:
            continue
        if target.image_id in {event.image_id for event in history[-3:]}:
            continue
        examples.append(TrainingExample(
            actor_key=key,
            history=history,
            target_image_id=target.image_id,
            target_behavior=target.behavior_type,
        ))
    return examples


def bootstrap_metadata(reason: str, sample_count: int = 0) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "model_name": "vibelo-sequence-recall",
        "model_version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "mode": "bootstrap",
        "reason": reason,
        "sample_count": sample_count,
        "recall_config": {
            "behaviorWeights": DEFAULT_BEHAVIOR_WEIGHTS,
            "timeHalfLifeHours": 336.0,
            "timeDecayFloor": 0.65,
            "durationBonus": 0.15,
            "durationCapMs": 120000,
            "minEventWeight": 0.001,
        },
        "metrics": {},
        "trained_at": now,
    }


def require_milvus_collection():
    try:
        from pymilvus import Collection, connections, utility
    except ImportError as exc:
        raise SystemExit("Install recommendation requirements first: pip install -r tools/requirements_recommendation.txt") from exc

    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
    if not utility.has_collection(MILVUS_COLLECTION):
        raise SystemExit(f"Milvus collection not found: {MILVUS_COLLECTION}")
    collection = Collection(MILVUS_COLLECTION)
    collection.load()
    return collection


def chunked(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def load_vectors(image_ids: Sequence[int]) -> Dict[int, np.ndarray]:
    ids = sorted({int(value) for value in image_ids if int(value) > 0})
    if not ids:
        return {}
    collection = require_milvus_collection()
    vectors: Dict[int, np.ndarray] = {}
    for batch in chunked(ids, 256):
        expr = "image_id in [{}]".format(",".join(str(item) for item in batch))
        rows = collection.query(expr=expr, output_fields=["image_id", VECTOR_FIELD])
        for row in rows:
            image_id = int(row.get("image_id") or 0)
            vector = row.get(VECTOR_FIELD)
            if image_id > 0 and vector is not None:
                array = np.asarray(vector, dtype=np.float32)
                norm = np.linalg.norm(array)
                if np.isfinite(norm) and norm > 0:
                    vectors[image_id] = (array / norm).astype(np.float32)
    return vectors


def candidate_configs() -> List[Dict[str, Any]]:
    configs: List[Dict[str, Any]] = []
    for half_life, duration_bonus, impression_weight, view_weight, click_weight in itertools.product(
        [72.0, 168.0, 336.0, 720.0],
        [0.0, 0.15, 0.30],
        [0.08, 0.18, 0.35],
        [1.2, 1.8, 2.4],
        [2.0, 2.8, 3.5],
    ):
        weights = dict(DEFAULT_BEHAVIOR_WEIGHTS)
        weights["impression"] = impression_weight
        weights["view"] = view_weight
        weights["click"] = click_weight
        configs.append({
            "behaviorWeights": weights,
            "timeHalfLifeHours": half_life,
            "timeDecayFloor": 0.62,
            "durationBonus": duration_bonus,
            "durationCapMs": 120000,
            "minEventWeight": 0.001,
        })
    return configs


def event_weight(event: BehaviorEvent, config: Dict[str, Any]) -> float:
    weights = config["behaviorWeights"]
    base = float(weights.get(event.behavior_type, 0.5))
    half_life_hours = max(1.0, float(config.get("timeHalfLifeHours") or 336.0))
    time_floor = clamp(float(config.get("timeDecayFloor") or 0.62), 0.0, 1.0)
    time_decay = math.pow(0.5, max(0, event.age_hours) / half_life_hours)
    duration_cap = max(1, int(config.get("durationCapMs") or 120000))
    duration_ratio = min(max(event.duration_ms, 0), duration_cap) / float(duration_cap)
    duration_bonus = max(0.0, float(config.get("durationBonus") or 0.0))
    min_weight = max(0.0, float(config.get("minEventWeight") or 0.001))
    return max(min_weight, base * (time_floor + (1.0 - time_floor) * time_decay) * (1.0 + duration_ratio * duration_bonus))


def interest_vector(example: TrainingExample, config: Dict[str, Any], vectors: Dict[int, np.ndarray]) -> Optional[np.ndarray]:
    weighted_vectors: List[np.ndarray] = []
    weights: List[float] = []
    seen: set[int] = set()
    for event in reversed(example.history):
        if event.image_id in seen:
            continue
        vector = vectors.get(event.image_id)
        if vector is None:
            continue
        weighted_vectors.append(vector)
        weights.append(event_weight(event, config))
        seen.add(event.image_id)
        if len(weighted_vectors) >= 80:
            break
    if not weighted_vectors:
        return None
    matrix = np.vstack(weighted_vectors).astype(np.float32)
    weight_array = np.asarray(weights, dtype=np.float32)
    vector = np.average(matrix, axis=0, weights=weight_array)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        return None
    return (vector / norm).astype(np.float32)


def evaluate_config(examples: Sequence[TrainingExample], config: Dict[str, Any], vectors: Dict[int, np.ndarray]) -> Dict[str, float]:
    query_vectors: List[np.ndarray] = []
    target_vectors: List[np.ndarray] = []
    for example in examples:
        target = vectors.get(example.target_image_id)
        if target is None:
            continue
        query = interest_vector(example, config, vectors)
        if query is None:
            continue
        query_vectors.append(query)
        target_vectors.append(target)
    if len(query_vectors) < 10:
        return {"valid_examples": float(len(query_vectors)), "mrr": 0.0, "hit10": 0.0, "hit50": 0.0, "mean_target_similarity": 0.0}
    query_matrix = np.vstack(query_vectors)
    target_matrix = np.vstack(target_vectors)
    scores = query_matrix @ target_matrix.T
    ranks = []
    for index in range(scores.shape[0]):
        own_score = scores[index, index]
        rank = int(np.sum(scores[index] > own_score) + 1)
        ranks.append(rank)
    rank_array = np.asarray(ranks, dtype=np.float32)
    return {
        "valid_examples": float(len(query_vectors)),
        "mrr": float(np.mean(1.0 / rank_array)),
        "hit10": float(np.mean(rank_array <= 10)),
        "hit50": float(np.mean(rank_array <= 50)),
        "mean_target_similarity": float(np.mean(np.diag(scores))),
    }


def train_behavior(args: argparse.Namespace) -> Dict[str, Any]:
    events = load_behavior_events(args.days, args.limit)
    examples = build_examples(events, args.min_history, args.max_history)
    if len(examples) < args.min_examples:
        if args.mode == "behavior":
            raise SystemExit(f"Only {len(examples)} recall examples found; collect more behavior logs first.")
        return bootstrap_metadata("not_enough_behavior_examples", sample_count=len(examples))

    random.Random(args.seed).shuffle(examples)
    examples = examples[:args.evaluation_sample]
    vector_ids = {example.target_image_id for example in examples}
    for example in examples:
        vector_ids.update(event.image_id for event in example.history)
    vectors = load_vectors(sorted(vector_ids))
    examples = [
        example for example in examples
        if example.target_image_id in vectors and any(event.image_id in vectors for event in example.history)
    ]
    if len(examples) < args.min_examples:
        if args.mode == "behavior":
            raise SystemExit(f"Only {len(examples)} examples have vectors; run vectorize_images.py first.")
        return bootstrap_metadata("not_enough_vectorized_examples", sample_count=len(examples))

    best_config: Optional[Dict[str, Any]] = None
    best_metrics: Optional[Dict[str, float]] = None
    best_score = -1.0
    tried = 0
    for config in candidate_configs():
        metrics = evaluate_config(examples, config, vectors)
        score = metrics["mrr"] * 0.60 + metrics["hit10"] * 0.25 + metrics["hit50"] * 0.10 + metrics["mean_target_similarity"] * 0.05
        tried += 1
        if score > best_score:
            best_score = score
            best_config = config
            best_metrics = metrics

    assert best_config is not None and best_metrics is not None
    return {
        "model_name": "vibelo-sequence-recall",
        "model_version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "mode": "behavior",
        "sample_count": len(examples),
        "event_count": len(events),
        "candidate_config_count": tried,
        "recall_config": best_config,
        "metrics": best_metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "milvus_collection": MILVUS_COLLECTION,
    }


def write_metadata(metadata: Dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RECALL_METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Vibelo sequence-aware recall weights.")
    parser.add_argument("--mode", choices=["auto", "behavior", "bootstrap"], default="auto")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--limit", type=int, default=300000)
    parser.add_argument("--min-examples", type=int, default=80)
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--max-history", type=int, default=120)
    parser.add_argument("--evaluation-sample", type=int, default=800)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mode == "bootstrap":
        metadata = bootstrap_metadata("manual_bootstrap")
    else:
        metadata = train_behavior(args)
    write_metadata(metadata, args.dry_run)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if not args.dry_run:
        print(f"Wrote {RECALL_METADATA_PATH}")


if __name__ == "__main__":
    main()
