#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sequence-aware recall and home ranking service for Vibelo recommendations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
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
TWO_TOWER_DIR = MODEL_DIR / "two_tower"
TWO_TOWER_REGISTRY_PATH = TWO_TOWER_DIR / "registry.json"
TWO_TOWER_DEVICE = os.environ.get("VIBELO_TWO_TOWER_DEVICE", "cpu")
TWO_TOWER_RETRY_SECONDS = max(1.0, float(os.environ.get("VIBELO_TWO_TOWER_RETRY_SECONDS", "30")))
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
    "interestCount": 3,
    "multiInterestMinEvents": 4,
    "clusterIterations": 4,
    "fusionK": 60,
}

app = FastAPI(title="Vibelo Recommendation Model Service")
_COLLECTIONS: Dict[str, Collection] = {}
_RANKER: Any = None
_RANKER_MTIME: Optional[float] = None
_RANKER_METADATA: Dict[str, Any] = {}
_RECALL_METADATA: Dict[str, Any] = {}
_RECALL_METADATA_MTIME: Optional[float] = None

_TWO_TOWER_MODEL: Any = None
_TWO_TOWER_PAYLOAD: Dict[str, Any] = {}
_TWO_TOWER_ENTRY: Dict[str, Any] = {}
_TWO_TOWER_REGISTRY_MTIME: Optional[int] = None
_TWO_TOWER_CHECKED = False
_TWO_TOWER_VERSION: Optional[str] = None
_TWO_TOWER_INDEX_COLLECTION: Optional[str] = None
_TWO_TOWER_LOAD_ERROR: Optional[str] = None
_TWO_TOWER_LOCK = threading.RLock()
_TWO_TOWER_LAST_CHECK_AT = 0.0

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
    mode: str = "heuristic"
    source: str = "siglip-multi-interest"
    modelVersion: Optional[str] = None
    indexCollection: Optional[str] = None


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


def collection(name: Optional[str] = None) -> Optional[Collection]:
    collection_name = str(name or MILVUS_COLLECTION)
    cached = _COLLECTIONS.get(collection_name)
    if cached is None:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        if not utility.has_collection(collection_name):
            return None
        cached = Collection(collection_name)
        cached.load()
        _COLLECTIONS[collection_name] = cached
    return cached


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


def _entry_value(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _entry_dict(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    try:
        return dict(vars(entry))
    except (TypeError, AttributeError):
        return {}


def _artifact_path(value: Any) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = TWO_TOWER_DIR / path
    resolved = path.resolve()
    base = TWO_TOWER_DIR.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("two-tower artifact path escapes model directory")
    return resolved

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _registry_mtime() -> Optional[int]:
    try:
        return TWO_TOWER_REGISTRY_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _two_tower_modules() -> Tuple[Any, Any]:
    try:
        from tools import two_tower_registry, two_tower_retrieval
    except ImportError:
        import two_tower_registry  # type: ignore
        import two_tower_retrieval  # type: ignore
    return two_tower_registry, two_tower_retrieval


def load_two_tower() -> Tuple[Any, Dict[str, Any], Optional[str]]:
    global _TWO_TOWER_MODEL
    global _TWO_TOWER_PAYLOAD
    global _TWO_TOWER_ENTRY
    global _TWO_TOWER_REGISTRY_MTIME
    global _TWO_TOWER_CHECKED
    global _TWO_TOWER_VERSION
    global _TWO_TOWER_LAST_CHECK_AT
    global _TWO_TOWER_INDEX_COLLECTION
    global _TWO_TOWER_LOAD_ERROR

    registry_mtime = _registry_mtime()
    checked_at = time.monotonic()
    with _TWO_TOWER_LOCK:
        if _TWO_TOWER_CHECKED and registry_mtime == _TWO_TOWER_REGISTRY_MTIME:
            if _TWO_TOWER_MODEL is not None:
                return _TWO_TOWER_MODEL, _TWO_TOWER_PAYLOAD, _TWO_TOWER_INDEX_COLLECTION
            if checked_at - _TWO_TOWER_LAST_CHECK_AT < TWO_TOWER_RETRY_SECONDS:
                return None, {}, None

        _TWO_TOWER_CHECKED = True
        _TWO_TOWER_REGISTRY_MTIME = registry_mtime
        _TWO_TOWER_MODEL = None
        _TWO_TOWER_PAYLOAD = {}
        _TWO_TOWER_LAST_CHECK_AT = checked_at
        _TWO_TOWER_ENTRY = {}
        _TWO_TOWER_VERSION = None
        _TWO_TOWER_INDEX_COLLECTION = None
        _TWO_TOWER_LOAD_ERROR = None

        if registry_mtime is None:
            _TWO_TOWER_LOAD_ERROR = "two-tower registry not found"
            return None, {}, None

        try:
            registry_module, retrieval_module = _two_tower_modules()
            entry = registry_module.get_entry("current", base_dir=MODEL_DIR)
            if entry is None:
                _TWO_TOWER_LOAD_ERROR = "no current two-tower model"
                return None, {}, None

            index = _entry_value(entry, "index", {})
            index_collection = (
                _entry_value(entry, "indexCollection")
                or _entry_value(index, "collection")
            )
            index_status = _entry_value(index, "status")
            index_entity_count = int(_entry_value(index, "entityCount", 0) or 0)
            if not index_collection:
                raise ValueError("current model has no index collection")
            if str(index_status or "").upper() != "READY":
                raise ValueError(f"current model index is not ready: {index_status}")
            if index_entity_count <= 0:
                raise ValueError("current model index has no entities")

            model_path_value = _entry_value(entry, "modelPath")
            if model_path_value:
                model_path = _artifact_path(model_path_value)
            else:
                artifact_dir = _entry_value(entry, "artifactDir")
                if not artifact_dir:
                    raise ValueError("current model has no artifact directory")
                model_path = _artifact_path(Path(str(artifact_dir)) / "model.pt")
            if not model_path.is_file():
                raise FileNotFoundError(f"two-tower checkpoint not found: {model_path}")

            manifest_path_value = _entry_value(entry, "manifestPath")
            if not manifest_path_value:
                raise ValueError("current model has no manifest path")
            manifest_path = _artifact_path(manifest_path_value)
            if not manifest_path.is_file():
                raise FileNotFoundError(f"two-tower manifest not found: {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("invalid two-tower manifest")
            training_metadata = manifest.get("training")
            data_metadata = manifest.get("data")
            if not isinstance(training_metadata, dict) \
                    or training_metadata.get("gatesPassed") is not True:
                raise ValueError("current two-tower model did not pass quality gates")
            if isinstance(data_metadata, dict) \
                    and data_metadata.get("mode") == "synthetic_smoke":
                raise ValueError("synthetic two-tower artifacts cannot serve")
            expected_sha256 = str(manifest.get("sha256") or "").strip().lower()
            if len(expected_sha256) != 64:
                raise ValueError("two-tower manifest has no valid checkpoint sha256")
            actual_sha256 = _sha256_file(model_path)
            if actual_sha256.lower() != expected_sha256:
                raise ValueError("two-tower checkpoint sha256 mismatch")
            entry_version = str(_entry_value(entry, "version") or "")
            if str(manifest.get("version") or "") != entry_version:
                raise ValueError("two-tower manifest version does not match registry")

            model, payload = retrieval_module.load_two_tower_checkpoint(
                model_path,
                device=TWO_TOWER_DEVICE,
            )
            if not isinstance(payload, dict):
                raise ValueError("invalid two-tower checkpoint payload")

            checkpoint_config = payload.get("config")
            if not isinstance(checkpoint_config, dict):
                raise ValueError("two-tower checkpoint has no config")
            if int(checkpoint_config.get("input_dim") or 0) != 512:
                raise ValueError("two-tower checkpoint input_dim must be 512")
            if int(checkpoint_config.get("embedding_dim") or 0) != 256:
                raise ValueError("two-tower checkpoint embedding_dim must be 256")
            if checkpoint_config != manifest.get("config"):
                raise ValueError("two-tower checkpoint config does not match manifest")
            if str(payload.get("version") or "") != entry_version:
                raise ValueError("two-tower checkpoint version does not match registry")

            _TWO_TOWER_MODEL = model
            _TWO_TOWER_PAYLOAD = payload
            _TWO_TOWER_ENTRY = _entry_dict(entry)
            _TWO_TOWER_VERSION = str(
                _entry_value(entry, "version")
                or payload.get("version")
                or "unknown"
            )
            _TWO_TOWER_INDEX_COLLECTION = str(index_collection)
            return _TWO_TOWER_MODEL, _TWO_TOWER_PAYLOAD, _TWO_TOWER_INDEX_COLLECTION
        except Exception as exc:
            _TWO_TOWER_MODEL = None
            _TWO_TOWER_PAYLOAD = {}
            _TWO_TOWER_ENTRY = {}
            _TWO_TOWER_VERSION = None
            _TWO_TOWER_INDEX_COLLECTION = None
            _TWO_TOWER_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
            return None, {}, None


def _config_int(config: Dict[str, Any], names: Sequence[str], default: int) -> int:
    for name in names:
        value = config.get(name)
        if value is not None:
            return int(value)
    return default


def trained_user_vector(events: Sequence[UserEvent]) -> Optional[np.ndarray]:
    model, payload, _ = load_two_tower()
    if model is None:
        return None

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    max_history = max(1, _config_int(
        config,
        ("max_sequence_length", "max_history", "maxHistory", "max_history_length"),
        50,
    ))
    min_history = max(2, _config_int(
        config,
        ("min_history", "minHistory", "min_history_events"),
        2,
    ))
    input_dimension = max(1, _config_int(
        config,
        ("input_dim", "input_dimension", "item_input_dimension", "itemInputDimension"),
        512,
    ))
    output_dimension = max(1, _config_int(
        config,
        ("embedding_dim", "output_dimension", "embedding_dimension", "outputDimension"),
        256,
    ))

    # The backend returns DESC events; training uses the same newest-first contract.
    newest_first = [
        event for event in events
        if event.imageId and event.imageId > 0
    ][:max_history]
    if len(newest_first) < min_history:
        return None
    vectors = query_vectors([event.imageId for event in newest_first])

    history_vectors: List[np.ndarray] = []
    behavior_names: List[str] = []
    age_hours: List[float] = []
    duration_ms: List[float] = []
    for event in newest_first:
        vector = vectors.get(int(event.imageId))
        if vector is None:
            continue
        flat = np.asarray(vector, dtype=np.float32).reshape(-1)
        if flat.size != input_dimension or not np.all(np.isfinite(flat)):
            raise ValueError(
                f"history vector dimension mismatch: expected {input_dimension}, got {flat.size}"
            )
        history_vectors.append(flat)
        behavior_names.append(str(event.behaviorType or "unknown"))
        age_hours.append(float(max(0, int(event.ageHours or 0))))
        duration_ms.append(float(max(0, int(event.durationMs or 0))))
    if len(history_vectors) < min_history:
        return None

    _, retrieval_module = _two_tower_modules()
    mapping = payload.get("behavior_to_id")
    behavior_ids = [
        int(retrieval_module.behavior_id(name, mapping=mapping))
        for name in behavior_names
    ]

    import torch
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


def user_interest_vectors(events: Sequence[UserEvent],
                          seed_ids: Sequence[int]) -> List[Tuple[np.ndarray, float]]:
    weighted_ids: List[Tuple[int, float]] = [
        (event.imageId, event_weight(event))
        for event in events
        if event.imageId and event.imageId > 0
    ]
    if not weighted_ids:
        weighted_ids = [(image_id, 1.0) for image_id in clean_ids(seed_ids, limit=80)]
    vectors = query_vectors([image_id for image_id, _ in weighted_ids])
    rows: List[np.ndarray] = []
    weights: List[float] = []
    for image_id, weight in weighted_ids:
        vector = vectors.get(image_id)
        if vector is None:
            continue
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            continue
        rows.append((vector / norm).astype(np.float32))
        weights.append(max(float(weight), 0.001))
    if not rows:
        return []

    matrix = np.vstack(rows).astype(np.float32)
    weight_array = np.asarray(weights, dtype=np.float32)
    config = recall_config()
    requested_count = max(1, min(5, int(config.get("interestCount") or 3)))
    min_events = max(2, int(config.get("multiInterestMinEvents") or 4))
    interest_count = 1 if len(rows) < min_events else min(requested_count, max(1, len(rows) // 2))

    def normalized_average(indices: np.ndarray) -> Optional[np.ndarray]:
        if indices.size == 0:
            return None
        center = np.average(matrix[indices], axis=0, weights=weight_array[indices])
        norm = np.linalg.norm(center)
        if not np.isfinite(norm) or norm <= 0:
            return None
        return (center / norm).astype(np.float32)

    if interest_count == 1:
        center = normalized_average(np.arange(len(rows)))
        return [] if center is None else [(center, 1.0)]

    selected = [int(np.argmax(weight_array))]
    while len(selected) < interest_count:
        similarities = matrix @ matrix[selected].T
        nearest = np.max(similarities, axis=1)
        nearest[selected] = np.inf
        selected.append(int(np.argmin(nearest)))
    centers = matrix[selected].copy()

    assignments = np.zeros(len(rows), dtype=np.int32)
    iterations = max(1, min(12, int(config.get("clusterIterations") or 4)))
    for _ in range(iterations):
        assignments = np.argmax(matrix @ centers.T, axis=1)
        updated = centers.copy()
        for cluster_index in range(interest_count):
            indices = np.flatnonzero(assignments == cluster_index)
            center = normalized_average(indices)
            if center is not None:
                updated[cluster_index] = center
        if np.allclose(updated, centers, atol=1e-5):
            centers = updated
            break
        centers = updated

    total_weight = max(float(np.sum(weight_array)), 0.001)
    interests: List[Tuple[np.ndarray, float]] = []
    for cluster_index in range(interest_count):
        indices = np.flatnonzero(assignments == cluster_index)
        if indices.size == 0:
            continue
        mass = float(np.sum(weight_array[indices])) / total_weight
        interests.append((centers[cluster_index].astype(np.float32), mass))
    interests.sort(key=lambda item: item[1], reverse=True)
    return interests


def search_interest_vectors(interests: Sequence[Tuple[np.ndarray, float]],
                            exclude_ids: Sequence[int],
                            offset: int,
                            limit: int) -> List[RecallHit]:
    safe_offset = normalize_offset(offset)
    safe_limit = normalize_limit(limit, MAX_RECALL_LIMIT)
    if not interests:
        return []
    if len(interests) == 1:
        return search_vector(interests[0][0], exclude_ids, safe_offset, safe_limit)

    candidate_limit = min(MAX_RECALL_LIMIT, max(safe_offset + safe_limit, safe_limit * len(interests)))
    fusion_k = max(10.0, float(recall_config().get("fusionK") or 60))
    fused: Dict[int, float] = {}
    for vector, interest_mass in interests:
        for rank, hit in enumerate(search_vector(vector, exclude_ids, 0, candidate_limit), start=1):
            semantic_score = max(-1.0, min(1.0, float(hit.score)))
            contribution = interest_mass * (1.0 / (fusion_k + rank) + 0.01 * (semantic_score + 1.0))
            fused[hit.imageId] = fused.get(hit.imageId, 0.0) + contribution
    ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [
        RecallHit(imageId=image_id, score=score)
        for image_id, score in ranked[safe_offset:safe_offset + safe_limit]
    ]


def _collection_vector_dimension(coll: Collection, vector_field: str) -> Optional[int]:
    schema = getattr(coll, "schema", None)
    for field in getattr(schema, "fields", []) or []:
        if getattr(field, "name", None) != vector_field:
            continue
        params = getattr(field, "params", {}) or {}
        dimension = params.get("dim")
        return None if dimension is None else int(dimension)
    return None


def search_vector(vector: np.ndarray,
                  exclude_ids: Sequence[int],
                  offset: int,
                  limit: int,
                  collection_name: Optional[str] = None,
                  vector_field: str = VECTOR_FIELD) -> List[RecallHit]:
    safe_offset = normalize_offset(offset)
    safe_limit = normalize_limit(limit, MAX_RECALL_LIMIT)
    coll = collection(collection_name)
    if coll is None:
        return []
    flat_vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    dimension = _collection_vector_dimension(coll, vector_field)
    if dimension is not None and flat_vector.size != dimension:
        raise ValueError(
            f"collection vector dimension mismatch: expected {dimension}, got {flat_vector.size}"
        )
    excluded = clean_ids(exclude_ids, limit=1000)
    expr = ""
    if excluded:
        expr = "image_id not in [{}]".format(",".join(str(item) for item in excluded))
    results = coll.search(
        data=[flat_vector.tolist()],
        anns_field=vector_field,
        param=SEARCH_PARAMS,
        limit=safe_offset + safe_limit,
        expr=expr or None,
        output_fields=["image_id"],
    )
    if not results:
        return []
    hits: List[RecallHit] = []
    for hit in results[0][safe_offset:safe_offset + safe_limit]:
        image_id = int(hit.entity.get("image_id"))
        hits.append(RecallHit(imageId=image_id, score=float(hit.score)))
    return hits


def trained_recall(events: Sequence[UserEvent],
                   exclude_ids: Sequence[int],
                   offset: int,
                   limit: int) -> Optional[List[RecallHit]]:
    global _TWO_TOWER_LOAD_ERROR

    try:
        model, _, index_collection = load_two_tower()
        if model is None or not index_collection:
            return None
        vector = trained_user_vector(events)
        if vector is None:
            return None
        learned_collection = collection(index_collection)
        if learned_collection is None:
            raise RuntimeError(f"two-tower index collection not found: {index_collection}")
        dimension = _collection_vector_dimension(learned_collection, VECTOR_FIELD)
        if dimension is not None and dimension != vector.size:
            raise ValueError(
                f"two-tower index dimension mismatch: expected {dimension}, got {vector.size}"
            )
        hits = search_vector(
            vector,
            exclude_ids,
            offset,
            limit,
            collection_name=index_collection,
            vector_field=VECTOR_FIELD,
        )
        with _TWO_TOWER_LOCK:
            _TWO_TOWER_LOAD_ERROR = None
        return hits
    except Exception as exc:
        with _TWO_TOWER_LOCK:
            if _TWO_TOWER_INDEX_COLLECTION:
                _COLLECTIONS.pop(_TWO_TOWER_INDEX_COLLECTION, None)
            _TWO_TOWER_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        return None


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
    two_tower_model, _, _ = load_two_tower()
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
        "twoTowerLoaded": two_tower_model is not None,
        "twoTowerVersion": _TWO_TOWER_VERSION,
        "twoTowerIndexCollection": _TWO_TOWER_INDEX_COLLECTION,
        "twoTowerLoadError": _TWO_TOWER_LOAD_ERROR,
    }


@app.post("/recall/home", response_model=RecallResponse)
def recall_home(request: HomeRecallRequest) -> RecallResponse:
    seed_ids = clean_ids(request.seedImageIds, limit=120)
    excluded = clean_ids([*request.excludeImageIds, *seed_ids], limit=1000)
    learned_hits = trained_recall(request.events, excluded, request.offset, request.limit)
    if learned_hits is not None:
        return RecallResponse(
            hits=learned_hits,
            mode="trained-two-tower",
            source="learned-two-tower",
            modelVersion=_TWO_TOWER_VERSION,
            indexCollection=_TWO_TOWER_INDEX_COLLECTION,
        )
    interests = user_interest_vectors(request.events, seed_ids)
    if not interests:
        return RecallResponse(hits=[], mode="heuristic", source="siglip-multi-interest")
    return RecallResponse(
        hits=search_interest_vectors(interests, excluded, request.offset, request.limit),
        mode="heuristic",
        source="siglip-multi-interest",
    )


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
