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
from typing import List

import torch
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from transformers import AutoModel, AutoProcessor


API_KEY = "VibeloGPU_20260606_SigLIP2"
MODEL_NAME = "google/siglip2-giant-opt-patch16-384"
MODEL_PATH = "/root/models/siglip2-giant-opt-patch16-384"
VECTOR_DIMENSION = 1536
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TORCH_DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32
MAX_BATCH_SIZE = 16

SERVICE_HOST = "0.0.0.0"
SERVICE_PORT = 6008

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

app = FastAPI(title="Vibelo SigLIP2 Embedding Service")
_processor = None
_model = None


class EmbedRequest(BaseModel):
    images: List[str] = Field(default_factory=list)


class EmbedResponse(BaseModel):
    model: str
    dimension: int
    vectors: List[List[float]]


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


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    auth(authorization)
    load_model()
    return {
        "ok": True,
        "model": MODEL_NAME,
        "source": model_source(),
        "dimension": VECTOR_DIMENSION,
        "device": DEVICE,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest, authorization: str | None = Header(default=None)):
    auth(authorization)
    if not request.images:
        return EmbedResponse(model=MODEL_NAME, dimension=VECTOR_DIMENSION, vectors=[])
    if len(request.images) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail="too many images in one batch")

    processor, model = load_model()
    images = [decode_image(item) for item in request.images]
    try:
        inputs = processor(images=images, return_tensors="pt", padding=True)
    except TypeError:
        inputs = processor(images=images, return_tensors="pt")
    inputs = {
        key: value.to(DEVICE, dtype=TORCH_DTYPE) if torch.is_floating_point(value) else value.to(DEVICE)
        for key, value in inputs.items()
    }
    with torch.inference_mode():
        if hasattr(model, "get_image_features"):
            features = model.get_image_features(**inputs)
        else:
            outputs = model.vision_model(pixel_values=inputs["pixel_values"])
            features = outputs.pooler_output
            projection = getattr(model, "visual_projection", None) or getattr(model, "vision_projection", None)
            if projection is not None:
                features = projection(features)
        features = features / features.norm(dim=-1, keepdim=True)
    vectors = features.detach().float().cpu().numpy().astype("float32")
    if vectors.shape[1] != VECTOR_DIMENSION:
        raise HTTPException(status_code=500, detail="bad vector dimension {}".format(vectors.shape[1]))
    return EmbedResponse(
        model=MODEL_NAME,
        dimension=VECTOR_DIMENSION,
        vectors=[vector.tolist() for vector in vectors],
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
