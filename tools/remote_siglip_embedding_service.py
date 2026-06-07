#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Remote GPU image embedding service for Vibelo.

Run this on the GPU server. It exposes a small HTTP API that returns normalized
SigLIP2 image embeddings. Local workers keep writing MySQL and Milvus.
"""

from __future__ import annotations

import base64
import io
import os
import time
from typing import List

import torch
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from transformers import AutoModel, AutoProcessor


API_KEY = "VibeloGPU_20260606_SigLIP2"
MODEL_NAME = "google/siglip2-giant-opt-patch16-384"
MODEL_PATH = "/root/models/siglip2-giant-opt-patch16-384"
VECTOR_DIMENSION = 512
PROJECTION_SEED = 20260606
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TORCH_DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32
MAX_BATCH_SIZE = 32

SERVICE_HOST = "0.0.0.0"
SERVICE_PORT = 6008

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

app = FastAPI(title="Vibelo SigLIP2 Embedding Service")
_processor = None
_model = None
_projection_matrix = None
_projection_input_dimension = None


class EmbedRequest(BaseModel):
    images: List[str] = Field(default_factory=list)


class EmbedResponse(BaseModel):
    model: str
    dimension: int
    vectors: List[List[float]]
    timings: dict[str, float] = Field(default_factory=dict)


def auth(authorization: str | None) -> None:
    expected = "Bearer " + API_KEY
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


def model_source() -> str:
    return MODEL_PATH if os.path.isdir(MODEL_PATH) else MODEL_NAME


def load_model():
    global _processor, _model
    if _processor is not None and _model is not None:
        return _processor, _model
    source = model_source()
    _processor = AutoProcessor.from_pretrained(source)
    _model = AutoModel.from_pretrained(source, torch_dtype=TORCH_DTYPE)
    _model.to(DEVICE)
    _model.eval()
    return _processor, _model


def decode_image(value: str) -> Image.Image:
    data = value.strip()
    if "," in data and data.lower().startswith("data:"):
        data = data.split(",", 1)[1]
    image_bytes = base64.b64decode(data)
    with Image.open(io.BytesIO(image_bytes)) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def as_feature_tensor(value):
    if torch.is_tensor(value):
        return value
    for attr in ("image_embeds", "pooler_output"):
        tensor = getattr(value, attr, None)
        if torch.is_tensor(tensor):
            return tensor
    last_hidden_state = getattr(value, "last_hidden_state", None)
    if torch.is_tensor(last_hidden_state):
        return last_hidden_state.mean(dim=1)
    if isinstance(value, (tuple, list)):
        for item in value:
            if torch.is_tensor(item):
                return item
            tensor = as_feature_tensor(item)
            if torch.is_tensor(tensor):
                return tensor
    raise RuntimeError("model did not return an image feature tensor: {}".format(type(value).__name__))


def l2_normalize(features):
    return features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)


def projection_matrix(input_dimension: int):
    global _projection_matrix, _projection_input_dimension
    if input_dimension == VECTOR_DIMENSION:
        return None
    if input_dimension < VECTOR_DIMENSION:
        raise RuntimeError("model vector dimension {} is smaller than configured {}".format(
            input_dimension,
            VECTOR_DIMENSION,
        ))
    if _projection_matrix is None or _projection_input_dimension != input_dimension:
        generator = torch.Generator()
        generator.manual_seed(PROJECTION_SEED)
        matrix = torch.randn(
            (input_dimension, VECTOR_DIMENSION),
            generator=generator,
            dtype=torch.float32,
        ) / (VECTOR_DIMENSION ** 0.5)
        _projection_matrix = matrix.to(DEVICE)
        _projection_input_dimension = input_dimension
    return _projection_matrix


def project_features(features):
    features = l2_normalize(features.float())
    matrix = projection_matrix(int(features.shape[-1]))
    if matrix is None:
        return l2_normalize(features)
    return l2_normalize(features @ matrix)


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    auth(authorization)
    load_model()
    return {
        "ok": True,
        "model": MODEL_NAME,
        "source": model_source(),
        "dimension": VECTOR_DIMENSION,
        "projection": "deterministic-random-projection",
        "projectionSeed": PROJECTION_SEED,
        "maxBatchSize": MAX_BATCH_SIZE,
        "device": DEVICE,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest, authorization: str | None = Header(default=None)):
    started_at = time.perf_counter()
    auth(authorization)
    if not request.images:
        return EmbedResponse(model=MODEL_NAME, dimension=VECTOR_DIMENSION, vectors=[])
    if len(request.images) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail="too many images in one batch")

    processor, model = load_model()
    loaded_at = time.perf_counter()
    images = [decode_image(item) for item in request.images]
    decoded_at = time.perf_counter()
    try:
        inputs = processor(images=images, return_tensors="pt", padding=True)
    except TypeError:
        inputs = processor(images=images, return_tensors="pt")
    inputs = {
        key: value.to(DEVICE, dtype=TORCH_DTYPE) if torch.is_floating_point(value) else value.to(DEVICE)
        for key, value in inputs.items()
    }
    preprocessed_at = time.perf_counter()
    with torch.inference_mode():
        if hasattr(model, "get_image_features"):
            features = as_feature_tensor(model.get_image_features(**inputs))
        else:
            outputs = model.vision_model(pixel_values=inputs["pixel_values"])
            features = as_feature_tensor(outputs)
            projection = getattr(model, "visual_projection", None) or getattr(model, "vision_projection", None)
            if projection is not None:
                features = projection(features)
        features = project_features(features)
    inferred_at = time.perf_counter()
    vectors = features.detach().float().cpu().numpy().astype("float32")
    if vectors.shape[1] != VECTOR_DIMENSION:
        raise HTTPException(status_code=500, detail="bad vector dimension {}".format(vectors.shape[1]))
    finished_at = time.perf_counter()
    return EmbedResponse(
        model=MODEL_NAME,
        dimension=VECTOR_DIMENSION,
        vectors=[vector.tolist() for vector in vectors],
        timings={
            "loadModel": round(loaded_at - started_at, 4),
            "decode": round(decoded_at - loaded_at, 4),
            "preprocess": round(preprocessed_at - decoded_at, 4),
            "infer": round(inferred_at - preprocessed_at, 4),
            "serialize": round(finished_at - inferred_at, 4),
            "total": round(finished_at - started_at, 4),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
