#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Cloud vision labeler: OpenAI-compatible VLM API -> MySQL annotations."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import sys
import time
import unicodedata
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]

IMPORT_RESULTS_PATH = ROOT / "tools" / "import_results.jsonl"
LABEL_RESULTS_PATH = ROOT / "tools" / "cloud_label_results.jsonl"
IMAGE_DIR = ROOT / "tools" / "downloaded_dataset" / "images"
LIMIT = int(os.environ.get("VIBELO_LABEL_LIMIT", "0") or "0")

MYSQL_HOST = os.environ.get("VIBELO_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("VIBELO_MYSQL_PORT", "3306") or "3306")
MYSQL_DATABASE = os.environ.get("VIBELO_MYSQL_DATABASE", "rangwaz_image_dev")
MYSQL_USER = os.environ.get("VIBELO_MYSQL_USER", "rangwaz")
MYSQL_PASSWORD = os.environ.get("VIBELO_MYSQL_PASSWORD", "rangwaz123")

CLOUD_API_BASE_URL = os.environ.get("VIBELO_CLOUD_LABEL_API_BASE_URL", "").strip()
CLOUD_API_KEY = os.environ.get("VIBELO_CLOUD_LABEL_API_KEY", "").strip()
CLOUD_MODEL = os.environ.get("VIBELO_CLOUD_LABEL_MODEL", "qwen3-vl-flash").strip()
CLOUD_PROXY_URL = os.environ.get("VIBELO_CLOUD_LABEL_PROXY_URL", "").strip()
SOURCE = ("cloud:" + CLOUD_MODEL)[:32]

LABEL_LANGUAGE = os.environ.get("VIBELO_LABEL_LANGUAGE", "zh")
MAX_TAGS = int(os.environ.get("VIBELO_LABEL_MAX_TAGS", "24") or "24")
MIN_TAGS_TO_SKIP = int(os.environ.get("VIBELO_LABEL_MIN_TAGS_TO_SKIP", "3") or "3")
MAX_WORKERS = int(os.environ.get("VIBELO_LABEL_WORKERS", "1") or "1")
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("VIBELO_LABEL_TIMEOUT_SECONDS", "180") or "180")
RETRY_ATTEMPTS = int(os.environ.get("VIBELO_LABEL_RETRY_ATTEMPTS", "4") or "4")
RETRY_BASE_DELAY_SECONDS = 1.5
RETRY_MAX_DELAY_SECONDS = 30.0
MAX_CONSECUTIVE_FAILURES = int(os.environ.get("VIBELO_LABEL_MAX_CONSECUTIVE_FAILURES", "80") or "80")
MODEL_IMAGE_MAX_SIDE = int(os.environ.get("VIBELO_LABEL_IMAGE_MAX_SIDE", "1024") or "1024")
MODEL_IMAGE_JPEG_QUALITY = int(os.environ.get("VIBELO_LABEL_JPEG_QUALITY", "85") or "85")
RESUME = os.environ.get("VIBELO_LABEL_RESUME", "1") != "0"
RETRY_FAILED_ON_RESUME = os.environ.get("VIBELO_LABEL_RETRY_FAILED", "1") != "0"
RELABEL_EXISTING = os.environ.get("VIBELO_LABEL_RELABEL_EXISTING", "0") == "1"
CLEAR_EXISTING_TAGS_ON_RELABEL = os.environ.get("VIBELO_LABEL_CLEAR_TAGS_ON_RELABEL", "0") == "1"
TRUST_RESULT_FILE_ON_RESUME = os.environ.get("VIBELO_LABEL_TRUST_RESULT_FILE", "0") == "1"
RESUME_FROM_LAST_ATTEMPT = os.environ.get("VIBELO_LABEL_RESUME_FROM_LAST_ATTEMPT", "1") != "0"
START_AFTER_SOURCE_INDEX = int(os.environ.get("VIBELO_LABEL_START_AFTER_SOURCE_INDEX", "0") or "0")

CATEGORY_CHOICES = [
    item.strip()
    for item in os.environ.get(
        "VIBELO_LABEL_CATEGORY_CHOICES",
        "人像,穿搭,美食,家居,建筑,旅行,自然风景,动物,植物,汽车,数码,动漫,游戏,艺术设计,摄影,体育,文字海报,其他",
    ).split(",")
    if item.strip()
]
ALLOWED_TAG_TYPES = {
    "subject",
    "scene",
    "style",
    "color",
    "object",
    "material",
    "mood",
    "composition",
    "quality",
    "text",
    "brand",
    "activity",
    "attribute",
}
TAG_TYPE_ALIASES = {
    "person": "subject",
    "people": "subject",
    "人物": "subject",
    "主体": "subject",
    "subject": "subject",
    "clothing": "object",
    "fashion": "style",
    "furniture": "object",
    "vehicle": "object",
    "car": "object",
    "food": "subject",
    "animal": "subject",
    "plant": "subject",
    "scene": "scene",
    "场景": "scene",
    "地点": "scene",
    "style": "style",
    "风格": "style",
    "color": "color",
    "颜色": "color",
    "object": "object",
    "objects": "object",
    "物体": "object",
    "material": "material",
    "材质": "material",
    "mood": "mood",
    "情绪": "mood",
    "氛围": "mood",
    "composition": "composition",
    "构图": "composition",
    "quality": "quality",
    "画质": "quality",
    "text": "text",
    "文字": "text",
    "brand": "brand",
    "品牌": "brand",
    "activity": "activity",
    "动作": "activity",
    "活动": "activity",
}

_PYMYSQL = None
_PIL_IMAGE = None
_IMAGE_FILE_INDEX: Optional[Dict[str, Path]] = None
_OPENER = build_opener(
    ProxyHandler({"http": CLOUD_PROXY_URL, "https": CLOUD_PROXY_URL} if CLOUD_PROXY_URL else {})
)


@dataclass(frozen=True)
class LabelJob:
    image_path: Path
    image_id: int
    source_index: int


@dataclass(frozen=True)
class ResumeState:
    attempted_image_ids: Set[int]
    ok_image_ids: Set[int]
    failed_image_ids: Set[int]


def resolve_imported_image_path(raw_path: object) -> Optional[Path]:
    image_path = Path(str(raw_path or ""))
    if image_path.name:
        fallback = image_file_index().get(image_path.name)
        if fallback:
            return fallback
    if image_path.exists():
        return image_path
    return None


def image_file_index() -> Dict[str, Path]:
    global _IMAGE_FILE_INDEX
    if _IMAGE_FILE_INDEX is None:
        if not IMAGE_DIR.exists():
            _IMAGE_FILE_INDEX = {}
        else:
            indexed: Dict[str, Path] = {}
            with os.scandir(IMAGE_DIR) as entries:
                for entry in entries:
                    if entry.is_file():
                        indexed[entry.name] = Path(entry.path)
            _IMAGE_FILE_INDEX = indexed
    return _IMAGE_FILE_INDEX


def require_dependencies():
    global _PYMYSQL
    if _PYMYSQL is not None:
        return _PYMYSQL
    try:
        import pymysql
    except Exception as exc:
        raise SystemExit("缺少 MySQL 依赖，请先安装 pymysql：{}".format(exc)) from exc
    _PYMYSQL = pymysql
    return pymysql


def require_pillow():
    global _PIL_IMAGE
    if _PIL_IMAGE is not None:
        return _PIL_IMAGE
    try:
        from PIL import Image, ImageOps
    except Exception:
        _PIL_IMAGE = False
        return None
    _PIL_IMAGE = (Image, ImageOps)
    return _PIL_IMAGE


def connect_mysql():
    pymysql = require_dependencies()
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def prompt_text() -> str:
    label_language = "Simplified Chinese" if LABEL_LANGUAGE.lower().startswith("zh") else "English"
    category_choices = "、".join(CATEGORY_CHOICES)
    tag_types = ", ".join(sorted(ALLOWED_TAG_TYPES - {"attribute"}))
    return f"""
Analyze this image for an image recommendation/search system.
Return only valid JSON, with no markdown.
Use {label_language} for category and tag names.
Use the exact English tag type namespaces listed below.

Schema:
{{
  "description": "one concise visible-content description, 12-40 Chinese characters if possible",
  "categoryPath": ["one stable broad category"],
  "tags": [
    {{"type": "one allowed tag type", "name": "visible label", "confidence": 0.0}}
  ]
}}

Rules:
- Infer labels from visible content only.
- categoryPath must contain exactly one broad category chosen from: {category_choices}.
- Allowed tag types: {tag_types}.
- tags should contain 8-16 useful independent facets when visible.
- Cover subject, scene, style, color, object, material, mood, composition, quality, text, brand, and activity when applicable.
- Put fine-grained subjects, styles, colors, scenes, devices, quality, and moods into tags, not categoryPath.
- confidence must be between 0 and 1.
- Do not return just one generic tag. Avoid duplicates and near-duplicates.
- Do not use broad fallback categories such as "wallpaper", "image", "picture", "material", or "unknown".
- Use "wallpaper" only when the image is clearly intended to be a wallpaper/background asset.
""".strip()


def encode_model_image(image_path: Path) -> str:
    pillow = require_pillow()
    if not pillow:
        return base64.b64encode(image_path.read_bytes()).decode("ascii")
    Image, ImageOps = pillow
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        image.thumbnail((MODEL_IMAGE_MAX_SIDE, MODEL_IMAGE_MAX_SIDE), resampling)
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            background = Image.new("RGB", image.size, (255, 255, 255))
            rgba = image.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=MODEL_IMAGE_JPEG_QUALITY, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def image_data_url(image_path: Path) -> str:
    return "data:image/jpeg;base64,{}".format(encode_model_image(image_path))


def request_payload(image_path: Path) -> Dict[str, object]:
    return {
        "model": CLOUD_MODEL,
        "temperature": 0.1,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text()},
                    {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
                ],
            }
        ],
    }


def parse_model_json(text: str) -> Dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("模型没有返回 JSON 对象")
    return value


def call_model_once(image_path: Path) -> Dict[str, object]:
    endpoint = urljoin(CLOUD_API_BASE_URL.rstrip("/") + "/", "chat/completions")
    request = Request(
        endpoint,
        data=json.dumps(request_payload(image_path)).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(CLOUD_API_KEY),
        },
        method="POST",
    )
    with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise RuntimeError("云端模型响应缺少 choices：{}".format(str(payload)[:1000]))
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                text_parts.append(str(item.get("text") or ""))
        content = "\n".join(text_parts)
    return parse_model_json(str(content or ""))


def is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
    if isinstance(exc, (URLError, TimeoutError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError):
        return getattr(exc, "winerror", None) in {10053, 10054, 10060, 10061} or getattr(exc, "errno", None) in {54, 104, 110, 111}
    return False


def readable_error(exc: BaseException) -> str:
    if not isinstance(exc, HTTPError):
        return str(exc)
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    detail = "HTTP {} {}".format(exc.code, getattr(exc, "reason", "") or "").strip()
    if body:
        detail += ": " + body[:2000]
    if exc.code == 404:
        detail += "；请检查 VIBELO_CLOUD_LABEL_API_BASE_URL 和 VIBELO_CLOUD_LABEL_MODEL 是否为支持图片输入的模型 ID"
    return detail


def retry_delay(attempt: int) -> float:
    delay = min(RETRY_MAX_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)))
    return delay + random.uniform(0, min(1.5, delay * 0.2))


def call_model(image_path: Path) -> Dict[str, object]:
    last_error: Optional[BaseException] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return call_model_once(image_path)
        except Exception as exc:
            last_error = exc
            if attempt >= RETRY_ATTEMPTS or not is_retryable_error(exc):
                break
            delay = retry_delay(attempt)
            print("  云端调用失败，{:.1f}s 后重试 {}/{}：{}".format(delay, attempt + 1, RETRY_ATTEMPTS, exc), file=sys.stderr)
            time.sleep(delay)
    assert last_error is not None
    raise RuntimeError(readable_error(last_error)) from last_error


def normalize_annotation(raw: Dict[str, object]) -> Dict[str, object]:
    raw_category = raw.get("categoryPath") or raw.get("category_path") or raw.get("categories") or []
    if isinstance(raw_category, str):
        category_path = [normalize_name(part, 64) for part in raw_category.replace("/", ">").split(">") if normalize_name(part, 64)]
    elif isinstance(raw_category, list):
        category_path = [normalize_name(part, 64) for part in raw_category if normalize_name(part, 64)]
    else:
        category_path = []
    if category_path and CATEGORY_CHOICES and category_path[0] not in CATEGORY_CHOICES:
        category_path = [closest_category(category_path[0])]
    tags_by_key: Dict[tuple, Dict[str, object]] = {}
    raw_tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    for item in raw_tags[:MAX_TAGS * 2]:
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get("name") or item.get("label"), 64)
        tag_type = normalize_tag_type(item.get("type"))
        if not name or not tag_type:
            continue
        try:
            confidence = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        clean_confidence = max(0.0, min(1.0, confidence))
        key = (tag_type, name)
        previous = tags_by_key.get(key)
        if previous is None or clean_confidence > float(previous["confidence"]):
            tags_by_key[key] = {"type": tag_type, "name": name, "confidence": clean_confidence, "source": SOURCE}
    tags = sorted(tags_by_key.values(), key=lambda item: float(item["confidence"]), reverse=True)[:MAX_TAGS]
    return {
        "description": str(raw.get("description") or "").strip(),
        "categoryPath": category_path[:1],
        "tags": tags,
        "source": SOURCE,
    }


def jobs_from_results() -> List[LabelJob]:
    if not IMPORT_RESULTS_PATH.exists():
        raise SystemExit("找不到导入结果文件：{}，请先运行 tools/import_images.py".format(IMPORT_RESULTS_PATH))
    jobs: List[LabelJob] = []
    with IMPORT_RESULTS_PATH.open("r", encoding="utf-8") as input_file:
        for source_index, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            image_id = row.get("imageId")
            if not row.get("ok") or not image_id:
                continue
            image_path = resolve_imported_image_path(row.get("path"))
            if image_path:
                jobs.append(LabelJob(image_path=image_path, image_id=int(image_id), source_index=source_index))
    unique: Dict[int, LabelJob] = {}
    for job in jobs:
        unique.setdefault(job.image_id, job)
    return list(unique.values())


def normalize_name(value: object, max_length: Optional[int] = None) -> str:
    text = " ".join(str(value or "").strip().lstrip("#").split())
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


def normalize_tag_type(value: object) -> str:
    raw = normalize_name(value, 32)
    if not raw:
        return "attribute"
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    mapped = TAG_TYPE_ALIASES.get(raw) or TAG_TYPE_ALIASES.get(key) or key
    if mapped not in ALLOWED_TAG_TYPES:
        return "attribute"
    return mapped


def closest_category(value: str) -> str:
    if not CATEGORY_CHOICES:
        return value
    clean = normalize_name(value, 64)
    if clean in CATEGORY_CHOICES:
        return clean
    for choice in CATEGORY_CHOICES:
        if choice in clean or clean in choice:
            return choice
    return CATEGORY_CHOICES[-1]


def slug(value: str, max_length: int = 120) -> str:
    normalized = normalize_name(value)
    ascii_value = unicodedata.normalize("NFD", normalized).encode("ascii", "ignore").decode("ascii")
    cleaned = []
    last_dash = False
    for char in ascii_value.lower():
        if char.isalnum():
            cleaned.append(char)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    text = "".join(cleaned).strip("-")
    if len(text) > max_length:
        text = text[:max_length].rstrip("-")
    return text or "key-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def stable_slug(value: str, *identity: str, max_length: int = 120) -> str:
    base = slug(value, max_length=max_length)
    digest_source = "\u0000".join(identity or (value,))
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    suffix = "-" + digest
    if len(base) + len(suffix) > max_length:
        base = base[:max(1, max_length - len(suffix))].rstrip("-")
    return (base or "key") + suffix


def confidence_value(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.8


def ensure_category_path(conn, raw_path: Iterable[str]) -> Optional[int]:
    names = []
    seen = set()
    for item in raw_path:
        name = normalize_name(item, 64)
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    if not names:
        return None
    name = names[0]
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM categories WHERE name=%s LIMIT 1", (name,))
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute("INSERT INTO categories(name,parent_id,slug,sort_no) VALUES(%s,NULL,%s,0)", (name, stable_slug(name, name)))
        return int(cursor.lastrowid)


def ensure_tag(conn, tag_type: str, name: str) -> Optional[int]:
    clean_type = normalize_tag_type(tag_type)
    clean_name = normalize_name(name, 64)
    if not clean_type or not clean_name:
        return None
    tag_slug = stable_slug(clean_type + "-" + clean_name, clean_type, clean_name)
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM tags WHERE type=%s AND name=%s LIMIT 1", (clean_type, clean_name))
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute("INSERT INTO tags(name,type,slug) VALUES(%s,%s,%s)", (clean_name, clean_type, tag_slug))
        return int(cursor.lastrowid)


def write_annotation(conn, image_id: int, annotation: Dict[str, object]) -> Dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM images WHERE id=%s LIMIT 1", (image_id,))
        image = cursor.fetchone()
        if not image:
            raise RuntimeError("images 表中找不到 image_id={}".format(image_id))
        image_id = int(image["id"])
        if CLEAR_EXISTING_TAGS_ON_RELABEL:
            cursor.execute("DELETE FROM image_tags WHERE image_id=%s", (image_id,))
    category_id = ensure_category_path(conn, annotation.get("categoryPath") or [])
    description = normalize_name(annotation.get("description"))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE images
            SET main_category_id=COALESCE(%s,main_category_id),
                description=COALESCE(NULLIF(%s,''),description)
            WHERE id=%s
            """,
            (category_id, description, image_id),
        )
    saved_tags = 0
    for tag in annotation.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        tag_id = ensure_tag(conn, str(tag.get("type") or ""), str(tag.get("name") or ""))
        if not tag_id:
            continue
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO image_tags(image_id,tag_id,confidence,source)
                VALUES(%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE confidence=GREATEST(confidence,VALUES(confidence)),source=VALUES(source)
                """,
                (image_id, tag_id, confidence_value(tag.get("confidence")), str(tag.get("source") or SOURCE)[:32]),
            )
        saved_tags += 1
    return {"imageId": image_id, "categoryId": category_id, "savedTags": saved_tags}


def write_result(payload: Dict[str, object]) -> None:
    LABEL_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABEL_RESULTS_PATH.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False) + "\n")


def resume_state_from_results() -> ResumeState:
    if not RESUME or not LABEL_RESULTS_PATH.exists():
        return ResumeState(attempted_image_ids=set(), ok_image_ids=set(), failed_image_ids=set())
    attempted: Set[int] = set()
    ok_ids: Set[int] = set()
    failed_ids: Set[int] = set()
    with LABEL_RESULTS_PATH.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not row.get("imageId"):
                continue
            image_id = int(row["imageId"])
            attempted.add(image_id)
            if row.get("ok"):
                ok_ids.add(image_id)
                failed_ids.discard(image_id)
            elif image_id not in ok_ids:
                failed_ids.add(image_id)
    return ResumeState(attempted_image_ids=attempted, ok_image_ids=ok_ids, failed_image_ids=failed_ids)


def result_file_complete_image_ids() -> Set[int]:
    if not TRUST_RESULT_FILE_ON_RESUME or not LABEL_RESULTS_PATH.exists():
        return set()
    complete_ids: Set[int] = set()
    with LABEL_RESULTS_PATH.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not row.get("ok") or not row.get("imageId"):
                continue
            annotation = row.get("annotation") if isinstance(row.get("annotation"), dict) else {}
            if annotation_complete(annotation):
                complete_ids.add(int(row["imageId"]))
    return complete_ids


def annotation_complete(annotation: Dict[str, object]) -> bool:
    description = normalize_name(annotation.get("description"))
    category_path = annotation.get("categoryPath") or []
    tags = annotation.get("tags") if isinstance(annotation.get("tags"), list) else []
    return bool(description) and bool(category_path) and len(tags) >= MIN_TAGS_TO_SKIP


def db_complete_labeled_image_ids(conn) -> Set[int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.id
            FROM images i
            LEFT JOIN image_tags it ON it.image_id=i.id
            GROUP BY i.id,i.description,i.main_category_id
            HAVING i.main_category_id IS NOT NULL
               AND i.description IS NOT NULL
               AND i.description <> ''
               AND COUNT(it.tag_id) >= %s
            """
            ,
            (MIN_TAGS_TO_SKIP,),
        )
        return {int(row["id"]) for row in cursor.fetchall()}


def submit_job(executor: ThreadPoolExecutor, job: LabelJob):
    future = executor.submit(call_model, job.image_path)
    return future


def require_cloud_config() -> None:
    if not CLOUD_API_BASE_URL:
        raise SystemExit("缺少 VIBELO_CLOUD_LABEL_API_BASE_URL，例如 https://dashscope.aliyuncs.com/compatible-mode/v1")
    if not CLOUD_API_KEY:
        raise SystemExit("缺少 VIBELO_CLOUD_LABEL_API_KEY。请用环境变量设置，不要写进代码。")
    print("云端打标模型：{}，API：{}".format(CLOUD_MODEL, CLOUD_API_BASE_URL))
    if CLOUD_PROXY_URL:
        print("云端打标请求走代理：{}".format(CLOUD_PROXY_URL))


def run() -> None:
    require_cloud_config()
    jobs = jobs_from_results()
    if not jobs:
        raise SystemExit("没有可标注的图片记录，请先运行 tools/import_images.py")
    if not RESUME and LABEL_RESULTS_PATH.exists():
        LABEL_RESULTS_PATH.unlink()
    ok = 0
    failed = 0
    consecutive_failed = 0
    with connect_mysql() as conn:
        total_jobs = len(jobs)
        if RESUME and not RELABEL_EXISTING:
            resume_state = resume_state_from_results()
            resume_cursor_index = START_AFTER_SOURCE_INDEX
            if RESUME_FROM_LAST_ATTEMPT and resume_state.attempted_image_ids:
                attempted_ids = resume_state.attempted_image_ids
                for job in jobs:
                    if job.image_id in attempted_ids and job.source_index > resume_cursor_index:
                        resume_cursor_index = job.source_index
            db_done_ids = db_complete_labeled_image_ids(conn)
            result_done_ids = result_file_complete_image_ids()
            skip_ids = set(db_done_ids) | result_done_ids
            if not RETRY_FAILED_ON_RESUME:
                skip_ids |= resume_state.attempted_image_ids
            jobs = [job for job in jobs if job.image_id not in skip_ids]
            if resume_cursor_index > 0:
                before_cursor = len(jobs)
                jobs = [job for job in jobs if job.source_index > resume_cursor_index]
                print("Resume cursor: source_index>{}, skipped_before_cursor={}".format(resume_cursor_index, before_cursor - len(jobs)))
            print(
                "断点续跑：结果文件成功 {} 张，数据库已完整标注 {} 张（至少 {} 个标签），本轮剩余 {} 张。".format(
                    len(resume_state.ok_image_ids),
                    len(db_done_ids),
                    MIN_TAGS_TO_SKIP,
                    len(jobs),
                )
            )
        if LIMIT:
            jobs = jobs[:LIMIT]
            print("Limit after skip: {}".format(len(jobs)))
        if not jobs:
            print("没有剩余需要标注的图片。")
            return
        with ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS)) as executor:
            pending: Dict[object, LabelJob] = {}
            job_iter = iter(jobs)
            submitted = 0
            while True:
                while len(pending) < max(1, MAX_WORKERS):
                    try:
                        job = next(job_iter)
                    except StopIteration:
                        break
                    submitted += 1
                    print("[{}/{} orig={}/{}] submit image={} {}".format(submitted, len(jobs), job.source_index, total_jobs, job.image_id, job.image_path))
                    pending[submit_job(executor, job)] = job
                if not pending:
                    break
                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    job = pending.pop(future)
                    try:
                        raw = future.result()
                        annotation = normalize_annotation(raw)
                        saved = write_annotation(conn, job.image_id, annotation)
                        conn.commit()
                        write_result({"ok": True, "imageId": job.image_id, "path": str(job.image_path), "annotation": annotation, "saved": saved})
                        ok += 1
                        consecutive_failed = 0
                    except Exception as exc:
                        conn.rollback()
                        failed += 1
                        consecutive_failed += 1
                        write_result({"ok": False, "imageId": job.image_id, "path": str(job.image_path), "error": str(exc)})
                        print("  失败 image={}：{}".format(job.image_id, exc), file=sys.stderr)
                        if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                            raise SystemExit("连续失败 {} 张，已停止。".format(consecutive_failed)) from exc
    print("完成：云端标注成功={}，失败={}，结果={}".format(ok, failed, LABEL_RESULTS_PATH))


if __name__ == "__main__":
    run()
