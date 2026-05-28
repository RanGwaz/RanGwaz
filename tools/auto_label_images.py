#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Development-only labeler: local vision model -> MySQL annotations directly."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]

# Edit these constants in code when the local development environment changes.
IMPORT_RESULTS_PATH = ROOT / "tools" / "import_results.jsonl"
LABEL_RESULTS_PATH = ROOT / "tools" / "auto_label_results.jsonl"
LIMIT = 0

MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_DATABASE = "rangwaz_image_dev"
MYSQL_USER = "rangwaz"
MYSQL_PASSWORD = "rangwaz123"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5vl:7b"
LABEL_LANGUAGE = "zh"
MAX_TAGS = 24
SOURCE = "ollama:" + OLLAMA_MODEL


@dataclass(frozen=True)
class LabelJob:
    image_path: Path
    image_id: int


_PYMYSQL = None


def require_dependencies():
    global _PYMYSQL
    if _PYMYSQL is not None:
        return _PYMYSQL
    try:
        import pymysql
    except Exception as exc:
        raise SystemExit("缺少 MySQL 依赖，请先执行：python -m pip install pymysql\n原始错误：{}".format(exc)) from exc
    _PYMYSQL = pymysql
    return pymysql


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
    return f"""
Analyze this image for an image recommendation/search system.
Return only valid JSON, with no markdown.
Use {label_language} for category and tag names.

Schema:
{{
  "description": "one concise visible-content description",
  "categoryPath": ["top category", "optional child", "optional child"],
  "tags": [
    {{"type": "short namespace", "name": "visible label", "confidence": 0.0}}
  ]
}}

Rules:
- Infer labels from visible content only.
- Do not use a fixed taxonomy; create concise labels that fit this specific image.
- categoryPath should contain 1 to 4 levels.
- tags should cover useful independent facets for retrieval when they are visible.
- confidence must be between 0 and 1.
- Do not use broad fallback categories such as "wallpaper", "image", "picture", "material", or "unknown".
- Use "wallpaper" only when the image is clearly intended to be a wallpaper/background asset.
""".strip()


def call_ollama(image_path: Path) -> Dict[str, object]:
    image_bytes = image_path.read_bytes()
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_text(),
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    request = Request(
        urljoin(OLLAMA_URL.rstrip("/") + "/", "/api/generate"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))
    return parse_model_json(str(result.get("response") or ""))


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
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("模型没有返回 JSON 对象")
    return value


def normalize_annotation(raw: Dict[str, object]) -> Dict[str, object]:
    raw_category = raw.get("categoryPath") or raw.get("category_path") or raw.get("categories") or []
    if isinstance(raw_category, str):
        category_path = [part.strip() for part in raw_category.replace("/", ">").split(">") if part.strip()]
    elif isinstance(raw_category, list):
        category_path = [str(part).strip() for part in raw_category if str(part).strip()]
    else:
        category_path = []

    tags: List[Dict[str, object]] = []
    raw_tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    for item in raw_tags[:MAX_TAGS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("label") or "").strip()
        tag_type = str(item.get("type") or "").strip()
        if not name or not tag_type:
            continue
        try:
            confidence = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        tags.append(
            {
                "type": tag_type,
                "name": name,
                "confidence": max(0.0, min(1.0, confidence)),
                "source": SOURCE,
            }
        )

    return {
        "description": str(raw.get("description") or "").strip(),
        "categoryPath": category_path[:4],
        "tags": tags,
        "source": SOURCE,
    }


def jobs_from_results() -> List[LabelJob]:
    if not IMPORT_RESULTS_PATH.exists():
        raise SystemExit("找不到导入结果文件：{}，请先运行 tools/import_images.py".format(IMPORT_RESULTS_PATH))
    jobs: List[LabelJob] = []
    with IMPORT_RESULTS_PATH.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            row = json.loads(line)
            image_id = row.get("imageId")
            if not row.get("ok") or not image_id:
                continue
            image_path = Path(str(row.get("path") or ""))
            if image_path.exists():
                jobs.append(LabelJob(image_path=image_path, image_id=int(image_id)))
    unique = {job.image_id: job for job in jobs}
    result = list(unique.values())
    return result[:LIMIT] if LIMIT else result


def normalize_name(value: object) -> str:
    return str(value or "").strip().lstrip("#")


def slug(value: str) -> str:
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
    if text:
        return text
    return "key-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def confidence_value(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.8


def ensure_category_path(conn, raw_path: Iterable[str]) -> Optional[int]:
    names = []
    seen = set()
    for item in raw_path:
        name = normalize_name(item)
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    if not names:
        return None

    parent_id = None
    slug_parts: List[str] = []
    current_id = None
    with conn.cursor() as cursor:
        for index, name in enumerate(names):
            slug_parts.append(slug(name))
            cursor.execute(
                """
                SELECT id FROM categories
                WHERE name=%s AND ((%s IS NULL AND parent_id IS NULL) OR parent_id=%s)
                LIMIT 1
                """,
                (name, parent_id, parent_id),
            )
            row = cursor.fetchone()
            if row:
                current_id = int(row["id"])
            else:
                cursor.execute(
                    "INSERT INTO categories(name,parent_id,slug,sort_no) VALUES(%s,%s,%s,%s)",
                    (name, parent_id, "-".join(slug_parts), index * 10),
                )
                current_id = int(cursor.lastrowid)
            parent_id = current_id
    return current_id


def ensure_tag(conn, tag_type: str, name: str) -> Optional[int]:
    clean_type = normalize_name(tag_type)
    clean_name = normalize_name(name)
    if not clean_type or not clean_name:
        return None
    tag_slug = clean_type + "-" + slug(clean_name)
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM tags WHERE type=%s AND name=%s LIMIT 1", (clean_type, clean_name))
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute(
            "INSERT INTO tags(name,type,slug) VALUES(%s,%s,%s)",
            (clean_name, clean_type, tag_slug),
        )
        return int(cursor.lastrowid)


def write_annotation(conn, image_id: int, annotation: Dict[str, object]) -> Dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM images WHERE id=%s LIMIT 1", (image_id,))
        image = cursor.fetchone()
        if not image:
            raise RuntimeError("images 表中找不到 image_id={}".format(image_id))
        image_id = int(image["id"])

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


def run() -> None:
    jobs = jobs_from_results()
    if not jobs:
        raise SystemExit("没有可标注的图片记录，请先运行 tools/import_images.py")
    if LABEL_RESULTS_PATH.exists():
        LABEL_RESULTS_PATH.unlink()

    ok = 0
    failed = 0
    with connect_mysql() as conn:
        for index, job in enumerate(jobs, start=1):
            print("[{}/{}] image={} {}".format(index, len(jobs), job.image_id, job.image_path))
            try:
                raw = call_ollama(job.image_path)
                annotation = normalize_annotation(raw)
                saved = write_annotation(conn, job.image_id, annotation)
                conn.commit()
                write_result(
                    {
                        "ok": True,
                        "imageId": job.image_id,
                        "path": str(job.image_path),
                        "annotation": annotation,
                        "saved": saved,
                    }
                )
                ok += 1
            except Exception as exc:
                conn.rollback()
                failed += 1
                write_result({"ok": False, "imageId": job.image_id, "path": str(job.image_path), "error": str(exc)})
                print("  失败：{}".format(exc), file=sys.stderr)
    print("完成：标注成功={}，失败={}，结果={}".format(ok, failed, LABEL_RESULTS_PATH))


if __name__ == "__main__":
    run()
