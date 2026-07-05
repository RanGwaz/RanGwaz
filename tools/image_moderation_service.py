#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lightweight local image moderation service for uploads.

Default mode uses cheap pixel heuristics. Set VIBELO_IMAGE_MODERATION_MODE=ollama
to add an open-weight vision model pass through Ollama, for example qwen3-vl:8b.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from PIL import Image
from pydantic import BaseModel

SERVICE_HOST = os.environ.get("VIBELO_IMAGE_MODERATION_HOST", "127.0.0.1")
SERVICE_PORT = int(os.environ.get("VIBELO_IMAGE_MODERATION_PORT", "8093"))
MODE = os.environ.get("VIBELO_IMAGE_MODERATION_MODE", "heuristic").strip().lower()
OLLAMA_URL = os.environ.get("VIBELO_OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("VIBELO_IMAGE_MODERATION_MODEL", "qwen3-vl:8b")
OLLAMA_TIMEOUT = float(os.environ.get("VIBELO_IMAGE_MODERATION_TIMEOUT", "20"))
FAIL_CLOSED = os.environ.get("VIBELO_IMAGE_MODERATION_FAIL_CLOSED", "true").strip().lower() != "false"
MAX_IMAGE_BYTES = int(os.environ.get("VIBELO_IMAGE_MODERATION_MAX_BYTES", str(8 * 1024 * 1024)))

UNSAFE_LABELS = {
    "pornography",
    "sexual",
    "nudity",
    "explicit",
    "gore",
    "bloody",
    "violence",
    "weapon",
    "illegal",
    "drug",
    "hate",
}

app = FastAPI(title="Vibelo Image Moderation Service")


class ModerateImageResponse(BaseModel):
    allowed: bool
    reason: str = "pass"
    labels: List[str] = []
    score: float = 0.0


def decode_image(payload: str) -> Tuple[bytes, Image.Image]:
    value = payload.split(",", 1)[1] if payload.startswith("data:") else payload
    try:
        image_bytes = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid imageBase64") from exc
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="image too large")
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="image decode failed") from exc
    return image_bytes, image


def sample_pixels(image: Image.Image, max_width: int = 192) -> List[Tuple[int, int, int]]:
    if image.width > max_width:
        height = max(1, round(image.height * max_width / image.width))
        image = image.resize((max_width, height))
    return list(image.getdata())


def is_skin_like(red: int, green: int, blue: int) -> bool:
    mx = max(red, green, blue)
    mn = min(red, green, blue)
    return red > 95 and green > 40 and blue > 20 and mx - mn > 15 and abs(red - green) > 15 and red > green and red > blue


def is_blood_like(red: int, green: int, blue: int) -> bool:
    return red >= 125 and red > green * 1.55 and red > blue * 1.45 and green < 105 and blue < 105


def heuristic_decision(image: Image.Image) -> ModerateImageResponse:
    pixels = sample_pixels(image)
    if not pixels:
        return ModerateImageResponse(allowed=True)
    total = len(pixels)
    skin = sum(1 for rgb in pixels if is_skin_like(*rgb))
    blood = sum(1 for rgb in pixels if is_blood_like(*rgb))
    skin_ratio = skin / total
    blood_ratio = blood / total
    if skin_ratio >= 0.58:
        return ModerateImageResponse(allowed=False, reason="possible-nudity", labels=["nudity"], score=skin_ratio)
    if blood_ratio >= 0.18:
        return ModerateImageResponse(allowed=False, reason="possible-bloody-violence", labels=["bloody", "violence"], score=blood_ratio)
    return ModerateImageResponse(allowed=True, reason="pass", labels=[], score=max(skin_ratio, blood_ratio))


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model did not return json")
    return json.loads(match.group(0))


def ollama_decision(image_base64: str) -> ModerateImageResponse:
    prompt = (
        "You are an image safety classifier. Return only JSON with keys: "
        "allowed(boolean), reason(string), labels(array), score(number). "
        "Block pornography, nudity, sexual content, bloody gore, realistic violence, weapons used for harm, illegal drugs, hate or extremist content. "
        "Allow ordinary portraits, fashion, art, travel, food, objects, and normal non-graphic images."
    )
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "images": [image_base64],
        "stream": False,
        "format": "json",
    }).encode("utf-8")
    request = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = extract_json(str(payload.get("response") or "{}"))
    labels = [str(item).strip().lower() for item in result.get("labels", []) if str(item).strip()]
    reason = str(result.get("reason") or "model-risk").strip()
    score = float(result.get("score") or 0)
    allowed = bool(result.get("allowed", True)) and not any(label in UNSAFE_LABELS for label in labels)
    return ModerateImageResponse(allowed=allowed, reason=reason if reason else "pass", labels=labels, score=score)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "mode": MODE, "model": OLLAMA_MODEL if MODE == "ollama" else "heuristic"}


@app.get("/")
def index() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "Vibelo Image Moderation Service",
        "health": "/health",
        "endpoint": "POST /moderate/image",
        "body": {"imageBase64": "base64 encoded image bytes", "contentType": "image/jpeg"},
        "mode": MODE,
    }


@app.post("/moderate/image", response_model=ModerateImageResponse)
async def moderate_image(request: Request) -> ModerateImageResponse:
    payload = await read_payload(request)
    image_base64 = first_payload_text(payload, "imageBase64", "image_base64", "base64", "image")
    if not image_base64:
        image_base64 = first_base64_like_text(payload)
    if not image_base64:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "missing imageBase64",
                "keys": sorted(str(key) for key in payload.keys()),
            },
        )
    _, image = decode_image(image_base64)
    heuristic = heuristic_decision(image)
    if not heuristic.allowed:
        return heuristic
    if MODE != "ollama":
        return heuristic
    try:
        return ollama_decision(image_base64)
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        if FAIL_CLOSED:
            return ModerateImageResponse(allowed=False, reason="model-unavailable", labels=["moderation-unavailable"], score=1.0)
        return ModerateImageResponse(allowed=True, reason="model-unavailable-fail-open", labels=[], score=0.0)


async def read_payload(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    raw = await request.body()
    if not raw:
        return {}
    if "application/json" in content_type:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid json body") from exc
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            return {"imageBase64": parsed}
        return {}
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        return {key: str(value) for key, value in form.items()}
    text = raw.decode("utf-8", errors="ignore").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    return {"imageBase64": text}


def first_payload_text(payload: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_base64_like_text(payload: Dict[str, Any]) -> str:
    for value in walk_values(payload):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) < 48:
            continue
        candidate = text.split(",", 1)[1] if text.startswith("data:") else text
        if re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", candidate):
            return text
    return ""


def walk_values(value: Any) -> List[Any]:
    if isinstance(value, dict):
        result: List[Any] = []
        for item in value.values():
            result.extend(walk_values(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(walk_values(item))
        return result
    return [value]


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Missing dependency: python -m pip install fastapi uvicorn pillow") from exc

    uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)
