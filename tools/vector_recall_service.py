#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HTTP recall service backed by Milvus image vectors."""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field
from pymilvus import Collection, connections, utility

MILVUS_HOST = "127.0.0.1"
MILVUS_PORT = "19530"
MILVUS_COLLECTION = "vibelo_image_vectors_siglip2_giant_p384"
VECTOR_FIELD = "embedding"
SEARCH_PARAMS = {"metric_type": "COSINE", "params": {"ef": 128}}
MAX_LIMIT = 200

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8091

app = FastAPI(title="Vibelo Vector Recall Service")
_COLLECTION: Optional[Collection] = None


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


def collection() -> Optional[Collection]:
    global _COLLECTION
    if _COLLECTION is None:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        if not utility.has_collection(MILVUS_COLLECTION):
            return None
        _COLLECTION = Collection(MILVUS_COLLECTION)
        _COLLECTION.load()
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
    return {"ok": coll is not None, "collection": MILVUS_COLLECTION, "entities": 0 if coll is None else coll.num_entities}


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
