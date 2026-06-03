#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Development-only labeler: local vision model -> MySQL annotations directly."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import shutil
import sys
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener

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
OLLAMA_EXE = ""
AUTO_START_OLLAMA = True
AUTO_PULL_OLLAMA_MODEL = True
OLLAMA_STARTUP_WAIT_SECONDS = 25
LABEL_LANGUAGE = "zh"
MAX_TAGS = 24
SOURCE = "ollama:" + OLLAMA_MODEL
RESUME = True
SKIP_ATTEMPTED_ON_RESUME = True
RETRY_FAILED_ON_RESUME = False
RETRY_ATTEMPTS = 5
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 45.0
OLLAMA_TIMEOUT_SECONDS = 300
MAX_CONSECUTIVE_FAILURES = 20
MODEL_IMAGE_MAX_SIDE = 1280
MODEL_IMAGE_JPEG_QUALITY = 88

# Ollama is local. Keep localhost traffic away from any system proxy.
for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(proxy_key, None)
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

_OLLAMA_OPENER = build_opener(ProxyHandler({}))
_PIL_IMAGE = None


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


_PYMYSQL = None


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
            background.paste(image.convert("RGBA"), mask=image.convert("RGBA").split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=MODEL_IMAGE_JPEG_QUALITY, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
    if isinstance(exc, (URLError, TimeoutError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError):
        return getattr(exc, "winerror", None) in {10053, 10054, 10060, 10061} or getattr(exc, "errno", None) in {54, 104, 110, 111}
    return False


def retry_delay(attempt: int) -> float:
    delay = min(RETRY_MAX_DELAY_SECONDS, RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)))
    return delay + random.uniform(0, min(1.5, delay * 0.2))


def call_ollama_once(image_path: Path) -> Dict[str, object]:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_text(),
        "images": [encode_model_image(image_path)],
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
    with _OLLAMA_OPENER.open(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        result = json.loads(response.read().decode("utf-8"))
    return parse_model_json(str(result.get("response") or ""))


def call_ollama(image_path: Path) -> Dict[str, object]:
    last_error: Optional[BaseException] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return call_ollama_once(image_path)
        except Exception as exc:
            last_error = exc
            if attempt >= RETRY_ATTEMPTS or not is_retryable_error(exc):
                break
            delay = retry_delay(attempt)
            print("  Ollama 调用失败，{:.1f}s 后重试 {}/{}：{}".format(delay, attempt + 1, RETRY_ATTEMPTS, exc), file=sys.stderr)
            time.sleep(delay)
    assert last_error is not None
    raise last_error


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
        for source_index, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            image_id = row.get("imageId")
            if not row.get("ok") or not image_id:
                continue
            image_path = Path(str(row.get("path") or ""))
            if image_path.exists():
                jobs.append(LabelJob(image_path=image_path, image_id=int(image_id), source_index=source_index))
    unique: Dict[int, LabelJob] = {}
    for job in jobs:
        unique.setdefault(job.image_id, job)
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


def find_ollama_exe() -> Optional[str]:
    if OLLAMA_EXE:
        candidate = Path(OLLAMA_EXE)
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def read_ollama_tags(timeout: int = 10) -> Dict[str, object]:
    request = Request(urljoin(OLLAMA_URL.rstrip("/") + "/", "/api/tags"), method="GET")
    with _OLLAMA_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ollama_model_names(payload: Dict[str, object]) -> Set[str]:
    models = payload.get("models") if isinstance(payload, dict) else []
    result: Set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = str(item.get(key) or "").strip()
            if value:
                result.add(value)
                result.add(value.split(":")[0])
    return result


def start_ollama_server(ollama_exe: str) -> None:
    if not AUTO_START_OLLAMA:
        return
    print("本机 Ollama 服务未响应，尝试启动 Ollama...")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [ollama_exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.time() + OLLAMA_STARTUP_WAIT_SECONDS
    while time.time() < deadline:
        try:
            read_ollama_tags(timeout=3)
            return
        except Exception:
            time.sleep(1)


def pull_ollama_model(ollama_exe: str) -> None:
    if not AUTO_PULL_OLLAMA_MODEL:
        raise SystemExit("缺少目标模型 {}，且 AUTO_PULL_OLLAMA_MODEL=False。".format(OLLAMA_MODEL))
    print("缺少目标模型 {}，开始下载。模型较大，请耐心等待...".format(OLLAMA_MODEL))
    process = subprocess.run([ollama_exe, "pull", OLLAMA_MODEL])
    if process.returncode != 0:
        raise SystemExit("目标模型 {} 下载失败，请检查网络或 Ollama 配置后重试。".format(OLLAMA_MODEL))


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


def db_labeled_image_ids(conn) -> Set[int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT i.id
            FROM images i
            LEFT JOIN image_tags it ON it.image_id=i.id AND it.source=%s
            WHERE (i.description IS NOT NULL AND i.description <> '')
               OR it.image_id IS NOT NULL
            """,
            (SOURCE[:32],),
        )
        return {int(row["id"]) for row in cursor.fetchall()}


def check_ollama_ready() -> None:
    ollama_exe = find_ollama_exe()
    try:
        payload = read_ollama_tags()
    except Exception as first_error:
        if not ollama_exe:
            raise SystemExit(
                "未找到 Ollama 运行时，脚本不会使用其它模型兜底。请先安装 Ollama，或把 OLLAMA_EXE 改成 ollama.exe 的完整路径。"
            ) from first_error
        start_ollama_server(ollama_exe)
        try:
            payload = read_ollama_tags()
        except Exception as second_error:
            raise SystemExit("无法连接本机 Ollama：{}。脚本不会使用其它模型兜底。".format(OLLAMA_URL)) from second_error

    names = ollama_model_names(payload)
    if OLLAMA_MODEL not in names and OLLAMA_MODEL.split(":")[0] not in names:
        if not ollama_exe:
            raise SystemExit("缺少目标模型 {}，且找不到 ollama.exe，无法自动下载。".format(OLLAMA_MODEL))
        pull_ollama_model(ollama_exe)
        payload = read_ollama_tags(timeout=30)
        names = ollama_model_names(payload)
        if OLLAMA_MODEL not in names and OLLAMA_MODEL.split(":")[0] not in names:
            raise SystemExit("目标模型 {} 下载后仍未出现在 Ollama 模型列表中。".format(OLLAMA_MODEL))


def run() -> None:
    jobs = jobs_from_results()
    if not jobs:
        raise SystemExit("没有可标注的图片记录，请先运行 tools/import_images.py")
    check_ollama_ready()
    if not RESUME and LABEL_RESULTS_PATH.exists():
        LABEL_RESULTS_PATH.unlink()

    ok = 0
    failed = 0
    consecutive_failed = 0
    with connect_mysql() as conn:
        total_jobs = len(jobs)
        if RESUME:
            resume_state = resume_state_from_results()
            db_done_ids = db_labeled_image_ids(conn)
            skip_ids = set(resume_state.ok_image_ids) | db_done_ids
            if SKIP_ATTEMPTED_ON_RESUME and not RETRY_FAILED_ON_RESUME:
                skip_ids |= resume_state.attempted_image_ids
            jobs = [job for job in jobs if job.image_id not in skip_ids]
            next_position = jobs[0].source_index if jobs else total_jobs + 1
            print(
                "断点续跑：结果文件已尝试 {} 张，成功 {} 张，失败待后续重试 {} 张；数据库已标注 {} 张；本轮剩余 {} 张，下一个源位置 {}/{}。".format(
                    len(resume_state.attempted_image_ids),
                    len(resume_state.ok_image_ids),
                    len(resume_state.failed_image_ids),
                    len(db_done_ids),
                    len(jobs),
                    min(next_position, total_jobs),
                    total_jobs,
                )
            )
        if not jobs:
            print("没有剩余需要标注的图片。")
            return

        for job in jobs:
            print("[{}/{}] image={} {}".format(job.source_index, total_jobs, job.image_id, job.image_path))
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
                consecutive_failed = 0
            except Exception as exc:
                conn.rollback()
                failed += 1
                consecutive_failed += 1
                write_result({"ok": False, "imageId": job.image_id, "path": str(job.image_path), "error": str(exc)})
                if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                    raise SystemExit(
                        "连续失败 {} 张，已停止，避免把 3 万张都刷成失败。请检查 Ollama/显存/代理后重新运行，脚本会断点续跑。".format(consecutive_failed)
                    ) from exc
                print("  失败：{}".format(exc), file=sys.stderr)
    print("完成：标注成功={}，失败={}，结果={}".format(ok, failed, LABEL_RESULTS_PATH))


if __name__ == "__main__":
    run()
