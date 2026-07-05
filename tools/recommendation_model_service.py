#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sequence-aware recall and home ranking service for Vibelo recommendations."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field
from pymilvus import Collection, connections, utility

MILVUS_HOST = os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("VIBELO_MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("VIBELO_MILVUS_COLLECTION", "vibelo_image_vectors_siglip2_base_p224_d512")
VECTOR_FIELD = "embedding"
SEARCH_PARAMS = {"metric_type": "COSINE", "params": {"ef": 128}}
MAX_RECALL_LIMIT = 240
MAX_RANK_LIMIT = 500

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get("VIBELO_RECOMMENDATION_MODEL_DIR", BASE_DIR / "models" / "recommendation"))
RANKER_PATH = MODEL_DIR / "ranker.joblib"
RANKER_METADATA_PATH = MODEL_DIR / "ranker_metadata.json"
RECALL_METADATA_PATH = MODEL_DIR / "recall_metadata.json"
SERVICE_HOST = os.environ.get("VIBELO_RECOMMENDATION_HOST", "127.0.0.1")
SERVICE_PORT = int(os.environ.get("VIBELO_RECOMMENDATION_PORT", "8092"))

FEATURE_NAMES = [
    "recall_score",
    "route_count",
    "engagement_score",
    "freshness_score",
    "metadata_quality_score",
    "recently_seen",
    "position_decay",
    "source_vector",
    "source_tag",
    "source_topic",
    "source_category",
    "source_follow",
    "source_global",
]

DEFAULT_BEHAVIOR_WEIGHTS = {
    "favorite": 5.0,
    "like": 4.0,
    "comment": 4.0,
    "share": 4.0,
    "click": 2.5,
    "view": 1.8,
    "impression": 0.35,
}
DEFAULT_RECALL_CONFIG = {
    "behaviorWeights": DEFAULT_BEHAVIOR_WEIGHTS,
    "timeHalfLifeHours": 336.0,
    "timeDecayFloor": 0.65,
    "durationBonus": 0.15,
    "durationCapMs": 120000,
    "minEventWeight": 0.001,
}

app = FastAPI(title="Vibelo Recommendation Model Service")
_COLLECTION: Optional[Collection] = None
_RANKER: Any = None
_RANKER_MTIME: Optional[float] = None
_RANKER_METADATA: Dict[str, Any] = {}
_RECALL_METADATA: Dict[str, Any] = {}
_RECALL_METADATA_MTIME: Optional[float] = None


class UserEvent(BaseModel):
    imageId: int
    behaviorType: str = "unknown"
    durationMs: Optional[int] = None
    ageHours: Optional[int] = None


class HomeRecallRequest(BaseModel):
    userId: Optional[int] = None
    events: List[UserEvent] = Field(default_factory=list)
    seedImageIds: List[int] = Field(default_factory=list)
    excludeImageIds: List[int] = Field(default_factory=list)
    offset: int = 0
    limit: int = 60
    refreshSeed: Optional[str] = None


class RecallHit(BaseModel):
    imageId: int
    score: float


class RecallResponse(BaseModel):
    hits: List[RecallHit]


class HomeRankCandidate(BaseModel):
    imageId: int
    recallScore: float = 0
    routeCount: int = 0
    primarySource: Optional[str] = None
    engagementScore: float = 0
    freshnessScore: float = 0
    metadataQualityScore: float = 0
    recentlySeen: bool = False
    authorId: Optional[int] = None
    categoryId: Optional[int] = None
    ratio: Optional[str] = None
    positionHint: Optional[int] = None


class HomeRankRequest(BaseModel):
    userId: Optional[int] = None
    scene: str = "home"
    requestId: Optional[str] = None
    refreshSeed: Optional[str] = None
    candidates: List[HomeRankCandidate] = Field(default_factory=list)
    limit: int = 60


class RankHit(BaseModel):
    imageId: int
    score: float
    reason: str


class RankResponse(BaseModel):
    modelName: str
    modelVersion: str
    hits: List[RankHit]


def collection() -> Optional[Collection]:
    global _COLLECTION
    if _COLLECTION is None:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        if not utility.has_collection(MILVUS_COLLECTION):
            return None
        _COLLECTION = Collection(MILVUS_COLLECTION)
        _COLLECTION.load()
    return _COLLECTION


def normalize_limit(value: int, max_limit: int) -> int:
    return max(1, min(max_limit, int(value or 1)))


def normalize_offset(value: int) -> int:
    return max(0, int(value or 0))


def clean_ids(values: Sequence[int], limit: int = 500) -> List[int]:
    result: List[int] = []
    seen = set()
    for value in values:
        try:
            image_id = int(value)
        except (TypeError, ValueError):
            continue
        if image_id <= 0 or image_id in seen:
            continue
        result.append(image_id)
        seen.add(image_id)
        if len(result) >= limit:
            break
    return result


def query_vectors(image_ids: Sequence[int]) -> Dict[int, np.ndarray]:
    ids = clean_ids(image_ids, limit=200)
    if not ids:
        return {}
    coll = collection()
    if coll is None:
        return {}
    expr = "image_id in [{}]".format(",".join(str(item) for item in ids))
    rows = coll.query(expr=expr, output_fields=["image_id", VECTOR_FIELD])
    vectors: Dict[int, np.ndarray] = {}
    for row in rows:
        vector = row.get(VECTOR_FIELD)
        image_id = row.get("image_id")
        if vector and image_id:
            vectors[int(image_id)] = np.asarray(vector, dtype=np.float32)
    return vectors


def load_recall_metadata() -> Dict[str, Any]:
    global _RECALL_METADATA, _RECALL_METADATA_MTIME
    if not RECALL_METADATA_PATH.exists():
        _RECALL_METADATA = {}
        _RECALL_METADATA_MTIME = None
        return {}
    mtime = RECALL_METADATA_PATH.stat().st_mtime
    if _RECALL_METADATA and _RECALL_METADATA_MTIME == mtime:
        return _RECALL_METADATA
    try:
        _RECALL_METADATA = json.loads(RECALL_METADATA_PATH.read_text(encoding="utf-8"))
        _RECALL_METADATA_MTIME = mtime
    except Exception:
        _RECALL_METADATA = {}
        _RECALL_METADATA_MTIME = None
    return _RECALL_METADATA


def recall_config() -> Dict[str, Any]:
    metadata = load_recall_metadata()
    config = metadata.get("recall_config") if isinstance(metadata, dict) else None
    if not isinstance(config, dict):
        return DEFAULT_RECALL_CONFIG
    merged = dict(DEFAULT_RECALL_CONFIG)
    merged.update(config)
    weights = dict(DEFAULT_BEHAVIOR_WEIGHTS)
    configured_weights = config.get("behaviorWeights")
    if isinstance(configured_weights, dict):
        weights.update({str(key): float(value) for key, value in configured_weights.items()})
    merged["behaviorWeights"] = weights
    return merged


def event_weight(event: UserEvent) -> float:
    config = recall_config()
    behavior_weights = config.get("behaviorWeights") or DEFAULT_BEHAVIOR_WEIGHTS
    behavior = (event.behaviorType or "unknown").lower()
    base = float(behavior_weights.get(behavior, 0.5))
    age_hours = max(0, int(event.ageHours or 0))
    half_life_hours = max(1.0, float(config.get("timeHalfLifeHours") or 336.0))
    time_floor = clamp(float(config.get("timeDecayFloor") or 0.65), 0, 1)
    time_decay = math.pow(0.5, age_hours / half_life_hours)
    duration_cap = max(1, int(config.get("durationCapMs") or 120000))
    duration_ratio = min(max(int(event.durationMs or 0), 0), duration_cap) / float(duration_cap)
    duration_bonus = max(0.0, float(config.get("durationBonus") or 0.0))
    min_event_weight = max(0.0, float(config.get("minEventWeight") or 0.001))
    return max(min_event_weight, base * (time_floor + (1.0 - time_floor) * time_decay) * (1.0 + duration_ratio * duration_bonus))


def behavior_weights() -> Dict[str, float]:
    return {key: float(value) for key, value in (recall_config().get("behaviorWeights") or DEFAULT_BEHAVIOR_WEIGHTS).items()}


def user_interest_vector(events: Sequence[UserEvent], seed_ids: Sequence[int]) -> Optional[np.ndarray]:
    weighted_ids: List[Tuple[int, float]] = []
    for event in events:
        if event.imageId and event.imageId > 0:
            weighted_ids.append((event.imageId, event_weight(event)))
    if not weighted_ids:
        weighted_ids = [(image_id, 1.0) for image_id in clean_ids(seed_ids, limit=80)]
    vectors = query_vectors([image_id for image_id, _ in weighted_ids])
    if not vectors:
        return None
    weighted_vectors = []
    weights = []
    for image_id, weight in weighted_ids:
        vector = vectors.get(image_id)
        if vector is None:
            continue
        weighted_vectors.append(vector)
        weights.append(max(weight, 0.001))
    if not weighted_vectors:
        return None
    matrix = np.vstack(weighted_vectors).astype(np.float32)
    weight_array = np.asarray(weights, dtype=np.float32)
    vector = np.average(matrix, axis=0, weights=weight_array)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        return None
    return (vector / norm).astype(np.float32)


def search_vector(vector: np.ndarray, exclude_ids: Sequence[int], offset: int, limit: int) -> List[RecallHit]:
    safe_offset = normalize_offset(offset)
    safe_limit = normalize_limit(limit, MAX_RECALL_LIMIT)
    coll = collection()
    if coll is None:
        return []
    excluded = clean_ids(exclude_ids, limit=1000)
    expr = ""
    if excluded:
        expr = "image_id not in [{}]".format(",".join(str(item) for item in excluded))
    results = coll.search(
        data=[vector.tolist()],
        anns_field=VECTOR_FIELD,
        param=SEARCH_PARAMS,
        limit=safe_offset + safe_limit,
        expr=expr or None,
        output_fields=["image_id"],
    )
    hits: List[RecallHit] = []
    for hit in results[0][safe_offset:safe_offset + safe_limit]:
        image_id = int(hit.entity.get("image_id"))
        hits.append(RecallHit(imageId=image_id, score=float(hit.score)))
    return hits


def stable_jitter(seed: Optional[str], image_id: int) -> float:
    payload = f"{seed or 'default'}:{image_id}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def clamp(value: float, low: float, high: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return low
    return min(high, max(low, float(value)))


def candidate_features(candidate: HomeRankCandidate) -> Dict[str, float]:
    source = (candidate.primarySource or "").lower()
    position = max(0, int(candidate.positionHint or 0))
    return {
        "recall_score": clamp(candidate.recallScore, 0, 4),
        "route_count": float(max(0, min(candidate.routeCount, 8))),
        "engagement_score": clamp(candidate.engagementScore, 0, 4),
        "freshness_score": clamp(candidate.freshnessScore, 0, 1),
        "metadata_quality_score": clamp(candidate.metadataQualityScore, 0, 2),
        "recently_seen": 1.0 if candidate.recentlySeen else 0.0,
        "position_decay": 1.0 / math.sqrt(position + 1.0),
        "source_vector": 1.0 if source == "vector" else 0.0,
        "source_tag": 1.0 if source == "tag" else 0.0,
        "source_topic": 1.0 if source == "topic" else 0.0,
        "source_category": 1.0 if source == "category" else 0.0,
        "source_follow": 1.0 if source == "follow" else 0.0,
        "source_global": 1.0 if source == "global" else 0.0,
    }


def load_ranker() -> Tuple[Any, Dict[str, Any]]:
    global _RANKER, _RANKER_MTIME, _RANKER_METADATA
    if not RANKER_PATH.exists():
        _RANKER = None
        _RANKER_MTIME = None
        _RANKER_METADATA = {}
        return None, {}
    mtime = RANKER_PATH.stat().st_mtime
    if _RANKER is not None and _RANKER_MTIME == mtime:
        return _RANKER, _RANKER_METADATA
    try:
        import joblib

        _RANKER = joblib.load(RANKER_PATH)
        _RANKER_MTIME = mtime
        if RANKER_METADATA_PATH.exists():
            _RANKER_METADATA = json.loads(RANKER_METADATA_PATH.read_text(encoding="utf-8"))
        else:
            _RANKER_METADATA = {}
    except Exception:
        _RANKER = None
        _RANKER_MTIME = None
        _RANKER_METADATA = {}
    return _RANKER, _RANKER_METADATA


def model_scores(candidates: Sequence[HomeRankCandidate]) -> Optional[List[float]]:
    ranker, metadata = load_ranker()
    if ranker is None:
        return None
    feature_names = metadata.get("feature_names") or FEATURE_NAMES
    matrix = []
    for candidate in candidates:
        features = candidate_features(candidate)
        matrix.append([features.get(name, 0.0) for name in feature_names])
    if not matrix:
        return []
    if hasattr(ranker, "predict_proba"):
        probabilities = ranker.predict_proba(matrix)
        return [float(row[-1]) for row in probabilities]
    return [float(score) for score in ranker.predict(matrix)]


def bootstrap_score(candidate: HomeRankCandidate, seed: Optional[str]) -> float:
    features = candidate_features(candidate)
    source_bonus = (
        features["source_vector"] * 0.05
        + features["source_tag"] * 0.025
        + features["source_topic"] * 0.02
        + features["source_follow"] * 0.035
        + features["source_global"] * 0.01
    )
    return (
        features["recall_score"] * 0.52
        + min(features["route_count"], 4) * 0.025
        + features["engagement_score"] * 0.18
        + features["freshness_score"] * 0.10
        + features["metadata_quality_score"] * 0.05
        + features["position_decay"] * 0.05
        + source_bonus
        - features["recently_seen"] * 0.30
        + stable_jitter(seed, candidate.imageId) * 0.045
    )


def diversify(scored: Sequence[Tuple[HomeRankCandidate, float]], limit: int) -> List[Tuple[HomeRankCandidate, float]]:
    remaining = list(scored)
    selected: List[Tuple[HomeRankCandidate, float]] = []
    author_counts: Dict[int, int] = {}
    category_counts: Dict[int, int] = {}
    while remaining and len(selected) < limit:
        best_index = 0
        best_adjusted = -float("inf")
        for index, (candidate, score) in enumerate(remaining):
            author_penalty = max(0, author_counts.get(candidate.authorId or -1, 0) - 1) * 0.035
            category_penalty = max(0, category_counts.get(candidate.categoryId or -1, 0) - 3) * 0.02
            adjusted = score - author_penalty - category_penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        candidate, score = remaining.pop(best_index)
        selected.append((candidate, score))
        if candidate.authorId is not None:
            author_counts[candidate.authorId] = author_counts.get(candidate.authorId, 0) + 1
        if candidate.categoryId is not None:
            category_counts[candidate.categoryId] = category_counts.get(candidate.categoryId, 0) + 1
    return selected


@app.get("/health")
def health() -> Dict[str, Any]:
    coll = collection()
    ranker, metadata = load_ranker()
    recall_metadata = load_recall_metadata()
    return {
        "ok": True,
        "milvusCollection": MILVUS_COLLECTION,
        "milvusReady": coll is not None,
        "milvusEntities": 0 if coll is None else coll.num_entities,
        "rankerLoaded": ranker is not None,
        "rankerPath": str(RANKER_PATH),
        "rankerMetadata": metadata,
        "recallMetadataPath": str(RECALL_METADATA_PATH),
        "recallMetadata": recall_metadata,
    }


@app.post("/recall/home", response_model=RecallResponse)
def recall_home(request: HomeRecallRequest) -> RecallResponse:
    seed_ids = clean_ids(request.seedImageIds, limit=120)
    excluded = clean_ids([*request.excludeImageIds, *seed_ids], limit=1000)
    vector = user_interest_vector(request.events, seed_ids)
    if vector is None:
        return RecallResponse(hits=[])
    return RecallResponse(hits=search_vector(vector, excluded, request.offset, request.limit))


@app.post("/rank/home", response_model=RankResponse)
def rank_home(request: HomeRankRequest) -> RankResponse:
    limit = normalize_limit(request.limit, MAX_RANK_LIMIT)
    candidates = request.candidates[:MAX_RANK_LIMIT]
    model_values = model_scores(candidates)
    if model_values is None:
        reason = "bootstrap-ranker"
        scored = [(candidate, bootstrap_score(candidate, request.refreshSeed or request.requestId)) for candidate in candidates]
        model_name = "vibelo-bootstrap-ranker"
        model_version = "v0"
    else:
        reason = "trained-ranker"
        scored = list(zip(candidates, model_values))
        metadata = _RANKER_METADATA or {}
        model_name = str(metadata.get("model_name") or "vibelo-home-ranker")
        model_version = str(metadata.get("model_version") or "v1")
    scored.sort(key=lambda item: item[1], reverse=True)
    ranked = diversify(scored, limit)
    hits = [RankHit(imageId=item.imageId, score=float(score), reason=reason) for item, score in ranked]
    return RankResponse(modelName=model_name, modelVersion=model_version, hits=hits)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
