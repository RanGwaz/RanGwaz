#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HTTP recall service backed by Milvus image vectors."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field
from pymilvus import Collection, connections, utility

MILVUS_HOST = os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("VIBELO_MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("VIBELO_MILVUS_COLLECTION", "vibelo_image_vectors_siglip2_base_p224_d512")
MODEL_NAME = os.environ.get("VIBELO_EMBED_MODEL", "google/siglip2-base-patch16-224")
VECTOR_VERSION = os.environ.get("VIBELO_EMBED_VECTOR_VERSION", "")
SUPPORTED_PROJECTION_VERSION = "siglip-image-feature-l2-rp512-seed20260606-v1"
PROJECTION_VERSION = os.environ.get(
    "VIBELO_EMBED_PROJECTION_VERSION", SUPPORTED_PROJECTION_VERSION
)
if PROJECTION_VERSION != SUPPORTED_PROJECTION_VERSION:
    raise SystemExit("VIBELO_EMBED_PROJECTION_VERSION does not match this recall service")
VECTOR_DIMENSION = 512
VECTOR_FIELD = "embedding"
SEARCH_PARAMS = {"metric_type": "COSINE", "params": {"ef": 128}}
MAX_LIMIT = max(1, min(1000, int(os.environ.get("VIBELO_VECTOR_RECALL_MAX_LIMIT", "240"))))
REQUIRE_READY_MARKER = os.environ.get("VIBELO_REQUIRE_VECTOR_READY_MARKER", "0") == "1"
READY_MARKER_PATH = Path(os.environ.get("VIBELO_VECTOR_READY_MARKER", "/data/vibelo-vector/state/ready.json"))


def validate_service_bind_host(value: str, require_private_bridge: bool) -> str:
    """Reject wildcard/public binds for the production host-side recall service."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise SystemExit("Vector recall bind host must be a literal IP address: {}".format(value)) from exc
    if address.version != 4 or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise SystemExit("Vector recall bind host is unsafe: {}".format(value))
    if require_private_bridge:
        private_networks = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
        if address.is_loopback or not any(address in network for network in private_networks):
            raise SystemExit("Vector recall must bind the discovered private Docker bridge gateway: {}".format(value))
    return str(address)


REQUIRE_PRIVATE_BRIDGE_BIND = os.environ.get("VIBELO_REQUIRE_PRIVATE_BRIDGE_BIND", "0") == "1"
SERVICE_HOST = validate_service_bind_host(
    os.environ.get("VIBELO_VECTOR_RECALL_HOST", "127.0.0.1"),
    REQUIRE_PRIVATE_BRIDGE_BIND,
)
SERVICE_PORT = int(os.environ.get("VIBELO_VECTOR_RECALL_PORT", "8091"))
if not 1 <= SERVICE_PORT <= 65535:
    raise SystemExit("VIBELO_VECTOR_RECALL_PORT must be between 1 and 65535")

app = FastAPI(title="Vibelo Vector Recall Service")
_COLLECTION: Optional[Collection] = None
_MARKER_SIGNATURE: Optional[tuple[int, int, int]] = None


class FeedRecallRequest(BaseModel):
    userId: Optional[int] = None
    seedImageIds: List[int] = Field(default_factory=list)
    offset: int = 0
    limit: int = 60


class SimilarRecallRequest(BaseModel):
    imageId: int
    offset: int = 0
    limit: int = 60


class VectorHit(BaseModel):
    imageId: int
    score: float


class VectorRecallResponse(BaseModel):
    hits: List[VectorHit]


def id_set_sha256(image_ids: set[int]) -> str:
    digest = hashlib.sha256()
    for image_id in sorted(image_ids):
        digest.update(str(image_id).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def collection_image_ids(coll: Collection) -> set[int]:
    result: set[int] = set()
    iterator = coll.query_iterator(batch_size=4096, expr="image_id > 0", output_fields=["image_id"])
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            for row in batch:
                image_id = int(row.get("image_id") or 0)
                if image_id <= 0 or image_id in result:
                    raise RuntimeError("invalid or duplicate image_id in Milvus")
                result.add(image_id)
    finally:
        iterator.close()
    return result


def validate_collection_artifact(coll: Collection) -> bool:
    field = next((item for item in coll.schema.fields if item.name == VECTOR_FIELD), None)
    if field is None or int((getattr(field, "params", {}) or {}).get("dim", 0) or 0) != VECTOR_DIMENSION:
        return False
    indexes = [item for item in (getattr(coll, "indexes", []) or []) if item.field_name == VECTOR_FIELD]
    if len(indexes) != 1:
        return False
    params = getattr(indexes[0], "params", {}) or {}
    return (
        str(params.get("metric_type") or "").upper() == "COSINE"
        and str(params.get("index_type") or "").upper() == "HNSW"
    )


def ready_marker() -> tuple[Optional[dict], Optional[tuple[int, int, int]]]:
    if not REQUIRE_READY_MARKER:
        return {}, None
    try:
        if READY_MARKER_PATH.is_symlink() or not READY_MARKER_PATH.is_file():
            return None, None
        before = READY_MARKER_PATH.stat()
        payload = json.loads(READY_MARKER_PATH.read_text(encoding="utf-8"))
        after = READY_MARKER_PATH.stat()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, None
    before_signature = (before.st_ino, before.st_mtime_ns, before.st_size)
    signature = (after.st_ino, after.st_mtime_ns, after.st_size)
    if signature != before_signature:
        return None, None
    expected = {
        "collection": MILVUS_COLLECTION,
        "dimension": VECTOR_DIMENSION,
        "metric": "COSINE",
        "model": MODEL_NAME,
        "projectionVersion": PROJECTION_VERSION,
        "vectorVersion": VECTOR_VERSION,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return None, None
    ready = payload.get("ready")
    entities = payload.get("entities")
    fingerprint = payload.get("idSetSha256")
    if (
        not isinstance(ready, int)
        or ready <= 0
        or entities != ready
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
    ):
        return None, None
    return payload, signature


def collection() -> Optional[Collection]:
    global _COLLECTION, _MARKER_SIGNATURE
    marker, signature = ready_marker()
    if marker is None:
        _COLLECTION = None
        _MARKER_SIGNATURE = None
        return None
    if _COLLECTION is not None:
        if signature == _MARKER_SIGNATURE:
            if not REQUIRE_READY_MARKER or int(_COLLECTION.num_entities) == int(marker["entities"]):
                return _COLLECTION
        _COLLECTION = None
        _MARKER_SIGNATURE = None
    if _COLLECTION is None:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        if not utility.has_collection(MILVUS_COLLECTION):
            return None
        candidate = Collection(MILVUS_COLLECTION)
        if not validate_collection_artifact(candidate):
            return None
        candidate.load()
        if REQUIRE_READY_MARKER:
            ids = collection_image_ids(candidate)
            if len(ids) != marker["entities"] or id_set_sha256(ids) != marker["idSetSha256"]:
                return None
        _COLLECTION = candidate
        _MARKER_SIGNATURE = signature
    return _COLLECTION


def normalize_limit(value: int) -> int:
    return max(1, min(MAX_LIMIT, int(value or 1)))


def normalize_offset(value: int) -> int:
    return max(0, int(value or 0))


def clean_ids(values: Sequence[int], limit: int = 100) -> List[int]:
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


def query_vectors(image_ids: Sequence[int]) -> List[np.ndarray]:
    ids = clean_ids(image_ids)
    if not ids:
        return []
    coll = collection()
    if coll is None:
        return []
    expr = "image_id in [{}]".format(",".join(str(item) for item in ids))
    rows = coll.query(expr=expr, output_fields=["image_id", VECTOR_FIELD])
    vectors = []
    for row in rows:
        vector = row.get(VECTOR_FIELD)
        if vector:
            vectors.append(np.asarray(vector, dtype=np.float32))
    return vectors


def average_vector(vectors: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    if not vectors:
        return None
    matrix = np.vstack(vectors).astype(np.float32)
    vector = matrix.mean(axis=0)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        return None
    return (vector / norm).astype(np.float32)


def search_vector(vector: np.ndarray, exclude_ids: Sequence[int], offset: int, limit: int) -> List[VectorHit]:
    safe_offset = normalize_offset(offset)
    safe_limit = normalize_limit(limit)
    search_limit = safe_offset + safe_limit
    coll = collection()
    if coll is None:
        return []
    expr = ""
    excluded = clean_ids(exclude_ids, limit=500)
    if excluded:
        expr = "image_id not in [{}]".format(",".join(str(item) for item in excluded))
    results = coll.search(
        data=[vector.tolist()],
        anns_field=VECTOR_FIELD,
        param=SEARCH_PARAMS,
        limit=search_limit,
        expr=expr or None,
        output_fields=["image_id"],
    )
    hits: List[VectorHit] = []
    for hit in results[0][safe_offset:safe_offset + safe_limit]:
        image_id = int(hit.entity.get("image_id"))
        hits.append(VectorHit(imageId=image_id, score=float(hit.score)))
    return hits


@app.get("/health")
def health():
    coll = collection()
    entities = 0 if coll is None else int(coll.num_entities)
    return {
        "ok": coll is not None and entities > 0,
        "collection": MILVUS_COLLECTION,
        "entities": entities,
        "readyMarkerRequired": REQUIRE_READY_MARKER,
    }


@app.post("/recall/feed", response_model=VectorRecallResponse)
def recall_feed(request: FeedRecallRequest):
    seed_ids = clean_ids(request.seedImageIds, limit=80)
    vector = average_vector(query_vectors(seed_ids))
    if vector is None:
        return VectorRecallResponse(hits=[])
    return VectorRecallResponse(hits=search_vector(vector, seed_ids, request.offset, request.limit))


@app.post("/recall/similar", response_model=VectorRecallResponse)
def recall_similar(request: SimilarRecallRequest):
    vectors = query_vectors([request.imageId])
    if not vectors:
        return VectorRecallResponse(hits=[])
    vector = average_vector(vectors)
    if vector is None:
        return VectorRecallResponse(hits=[])
    return VectorRecallResponse(hits=search_vector(vector, [request.imageId], request.offset, request.limit))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
