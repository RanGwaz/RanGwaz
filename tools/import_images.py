#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Idempotent operator importer: staged images -> MinIO + MySQL.

The importer never creates or rebuilds the database schema. Production secrets
must be supplied through environment variables rather than source code.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]


def env_value(primary: str, fallback: str, default: str = "") -> str:
    """Read the canonical variable first, then a legacy compatibility name."""
    return os.environ.get(primary) or os.environ.get(fallback) or default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("{} must be a positive integer".format(name)) from exc
    if value <= 0:
        raise SystemExit("{} must be a positive integer".format(name))
    return value


def env_nonnegative_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("{} must be a non-negative integer".format(name)) from exc
    if value < 0:
        raise SystemExit("{} must be a non-negative integer".format(name))
    return value


def env_bounded_positive_int(name: str, default: int, maximum: int) -> int:
    value = env_positive_int(name, default)
    if value > maximum:
        raise SystemExit("{} must not exceed {}".format(name, maximum))
    return value


IMAGE_DIR = Path(os.environ.get("VIBELO_DATASET_IMAGE_DIR", str(ROOT / "tools" / "downloaded_dataset" / "images")))
PROCESSED_DIR = Path(
    os.environ.get("VIBELO_IMPORT_PROCESSED_DIR", str(IMAGE_DIR.parent / "processed"))
)
RESULT_PATH = Path(os.environ.get("VIBELO_IMPORT_RESULT_PATH", str(ROOT / "tools" / "import_results.jsonl")))
SUMMARY_PATH = Path(os.environ["VIBELO_IMPORT_SUMMARY_PATH"]) if os.environ.get("VIBELO_IMPORT_SUMMARY_PATH") else None
RECURSIVE = env_bool("VIBELO_IMPORT_RECURSIVE")
LIMIT = env_bounded_positive_int("VIBELO_IMPORT_LIMIT", 500, 500)
RESUME_IMPORT_RESULTS = env_bool("VIBELO_IMPORT_RESUME", True)
MIN_FREE_BYTES = env_nonnegative_int("VIBELO_IMPORT_MIN_FREE_BYTES", 0)
STORAGE_CHECK_PATH = Path(os.environ.get("VIBELO_IMPORT_STORAGE_CHECK_PATH", "/data"))

IMPORT_AUTHOR_ID = int(os.environ.get("VIBELO_IMPORT_AUTHOR_ID", "0") or "0")
IMPORT_USERNAME = os.environ.get("VIBELO_IMPORT_USERNAME", "mira").strip()
DEFAULT_IMAGE_CONTENT = os.environ.get("VIBELO_IMPORT_DEFAULT_CONTENT", "Imported image")
IMAGE_TITLE_PREFIX = os.environ.get("VIBELO_IMPORT_TITLE_PREFIX", "")

MYSQL_HOST = env_value("VIBELO_DB_HOST", "VIBELO_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(env_value("VIBELO_DB_PORT", "VIBELO_MYSQL_PORT", "3306"))
MYSQL_DATABASE = env_value("VIBELO_DB_NAME", "VIBELO_MYSQL_DATABASE", "rangwaz_image_dev")
MYSQL_USER = env_value("VIBELO_DB_USER", "VIBELO_MYSQL_USER", "vibelo_app")
MYSQL_PASSWORD = env_value("VIBELO_DB_PASSWORD", "VIBELO_MYSQL_PASSWORD", "")

MINIO_ENDPOINT = os.environ.get("VIBELO_MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = env_value("MINIO_ACCESS_KEY", "VIBELO_MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = env_value("MINIO_SECRET_KEY", "VIBELO_MINIO_SECRET_KEY")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "rangwaz-media")
MINIO_SECURE = env_bool("VIBELO_MINIO_SECURE")
MEDIA_OBJECT_PREFIX = os.environ.get("VIBELO_MEDIA_OBJECT_PREFIX", "/media/object")

THUMBNAIL_MAX_WIDTH = 520
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
    "BMP": ("image/bmp", ".bmp"),
}
MAX_FILE_BYTES = env_bounded_positive_int("VIBELO_IMPORT_MAX_FILE_BYTES", 25 * 1024 * 1024, 25 * 1024 * 1024)
MAX_IMAGE_PIXELS = env_bounded_positive_int("VIBELO_IMPORT_MAX_IMAGE_PIXELS", 40_000_000, 40_000_000)
MAX_IMAGE_DIMENSION = env_bounded_positive_int("VIBELO_IMPORT_MAX_IMAGE_DIMENSION", 16_384, 16_384)
_DEPS = None


class ImportCapacityError(RuntimeError):
    """The public data-disk reserve has been crossed; stop the whole batch."""


def require_dependencies():
    global _DEPS
    if _DEPS is not None:
        return _DEPS
    try:
        import pymysql
        from minio import Minio
        from PIL import Image, ImageOps
    except Exception as exc:
        raise SystemExit(
            "缺少导入依赖，请按 tools/requirements_content_jobs.txt 准备独立环境\n"
            "原始错误：{}".format(exc)
        ) from exc
    _DEPS = (pymysql, Minio, Image, ImageOps)
    return _DEPS


def connect_mysql():
    pymysql, _, _, _ = require_dependencies()
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


def minio_client():
    _, Minio, _, _ = require_dependencies()
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def ensure_bucket(client) -> None:
    if not client.bucket_exists(MINIO_BUCKET):
        raise RuntimeError("MinIO bucket does not exist: {}".format(MINIO_BUCKET))


def ensure_import_user(conn) -> int:
    if IMPORT_AUTHOR_ID > 0:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM app_users WHERE id=%s AND status='ACTIVE'", (IMPORT_AUTHOR_ID,))
            row = cursor.fetchone()
        if not row:
            raise RuntimeError("Configured import author is missing or inactive: {}".format(IMPORT_AUTHOR_ID))
        return int(row["id"])
    if not IMPORT_USERNAME:
        raise RuntimeError("Set VIBELO_IMPORT_AUTHOR_ID or VIBELO_IMPORT_USERNAME")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM app_users WHERE username=%s AND status='ACTIVE'",
            (IMPORT_USERNAME,),
        )
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        raise RuntimeError(
            "Import user is missing or inactive; create or activate the business author through the application first"
        )


def table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
            """,
            (table_name,),
        )
        return int(cursor.fetchone()["total"]) > 0


def column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s
            """,
            (table_name, column_name),
        )
        return int(cursor.fetchone()["total"]) > 0


def ensure_database_schema(conn) -> None:
    needs_rebuild = (
        not table_exists(conn, "images")
        or not column_exists(conn, "images", "author_id")
        or table_exists(conn, "posts")
        or not table_exists(conn, "image_topics")
    )
    if not needs_rebuild:
        return
    raise SystemExit("数据库结构不符合当前版本；导入器禁止自动建表或删表，请先运行受控 Flyway 迁移")


def image_files() -> List[Path]:
    pattern = "**/*" if RECURSIVE else "*"
    files = [
        path
        for path in IMAGE_DIR.glob(pattern)
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(files)


def ensure_import_capacity() -> None:
    """Recheck the public data disk before every newly attempted file."""
    if MIN_FREE_BYTES <= 0:
        return
    try:
        free_bytes = int(shutil.disk_usage(STORAGE_CHECK_PATH).free)
    except OSError as exc:
        raise ImportCapacityError(
            "cannot read free space for {}".format(STORAGE_CHECK_PATH)
        ) from exc
    if free_bytes < MIN_FREE_BYTES:
        raise ImportCapacityError(
            "data disk free space {} is below required {} bytes".format(
                free_bytes,
                MIN_FREE_BYTES,
            )
        )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_image_info(data: bytes) -> Tuple[int, int, bytes, str, str]:
    _, _, Image, ImageOps = require_dependencies()
    with Image.open(BytesIO(data)) as probe:
        image_format = str(probe.format or "").upper()
        if image_format not in IMAGE_FORMATS:
            raise ValueError("unsupported image format: {}".format(image_format or "unknown"))
        width, height = probe.size
        if width <= 0 or height <= 0:
            raise ValueError("image dimensions must be positive")
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
            raise ValueError(
                "image dimensions {}x{} exceed configured limits".format(width, height)
            )
        probe.verify()
    with Image.open(BytesIO(data)) as image:
        image.load()
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        thumb = image.copy()
        if thumb.width > THUMBNAIL_MAX_WIDTH:
            next_height = max(1, round(thumb.height * THUMBNAIL_MAX_WIDTH / thumb.width))
            thumb = thumb.resize((THUMBNAIL_MAX_WIDTH, next_height))
        if thumb.mode not in ("RGB", "L"):
            background = Image.new("RGB", thumb.size, "white")
            if "A" in thumb.getbands():
                background.paste(thumb, mask=thumb.getchannel("A"))
            else:
                background.paste(thumb)
            thumb = background
        else:
            thumb = thumb.convert("RGB")
        output = BytesIO()
        thumb.save(output, format="JPEG", quality=86, optimize=True)
        mime, suffix = IMAGE_FORMATS[image_format]
        return width, height, output.getvalue(), mime, suffix


def public_url(object_key: str) -> str:
    return MEDIA_OBJECT_PREFIX.rstrip("/") + "/" + object_key


def put_object(client, object_key: str, data: bytes, mime: str) -> None:
    client.put_object(
        MINIO_BUCKET,
        object_key,
        BytesIO(data),
        length=len(data),
        content_type=mime,
    )


def object_keys(digest: str, suffix: str) -> Tuple[str, str]:
    """Return stable object keys so a retry safely overwrites the same payload."""
    shard = digest[:2]
    return (
        "originals/sha256/{}/{}{}".format(shard, digest, suffix),
        "thumbs/sha256/{}/{}.jpg".format(shard, digest),
    )


def ratio_label(width: Optional[int], height: Optional[int]) -> Optional[str]:
    if not width or not height or width <= 0 or height <= 0:
        return None
    divisor = gcd(width, height)
    left = width // divisor
    right = height // divisor
    if left > 80 or right > 80:
        decimal = "{:.4f}".format(width / height).rstrip("0").rstrip(".")
        return decimal + ":1"
    return "{}:{}".format(left, right)


def gcd(left: int, right: int) -> int:
    a = abs(left)
    b = abs(right)
    while b:
        a, b = b, a % b
    return max(a, 1)


def find_existing_image(conn, digest: str) -> Optional[Dict[str, object]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id AS image_id,object_key,file_url
            FROM images
            WHERE hash=%s
            LIMIT 1
            """,
            (digest,),
        )
        return cursor.fetchone()


def insert_image_rows(
    conn,
    author_id: int,
    file_path: Path,
    original_key: str,
    thumb_key: str,
    width: int,
    height: int,
    file_size: int,
    digest: str,
    mime: str,
) -> Dict[str, object]:
    file_url = public_url(original_key)
    thumb_url = public_url(thumb_key)
    title = (IMAGE_TITLE_PREFIX + file_path.stem).strip()[:160] or file_path.name[:160]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO images(author_id,title,content,post_type,description,object_key,file_url,file_type,thumbnail_url,
                               width,height,ratio,file_size,hash,main_category_id,status,
                               like_count,favorite_count,comment_count,share_count,view_count,hot_score,published_at)
            VALUES(%s,%s,%s,'image',NULL,%s,%s,'image',%s,%s,%s,%s,%s,%s,NULL,'PENDING_REVIEW',
                   0,0,0,0,0,0,NULL)
            """,
            (
                author_id,
                title,
                DEFAULT_IMAGE_CONTENT,
                original_key,
                file_url,
                thumb_url,
                width,
                height,
                ratio_label(width, height),
                file_size,
                digest,
            ),
        )
        image_id = int(cursor.lastrowid)
    return {
        "imageId": image_id,
        "objectKey": original_key,
        "fileUrl": file_url,
        "thumbnailUrl": thumb_url,
        "width": width,
        "height": height,
        "fileSize": file_size,
        "hash": digest,
        "contentType": mime,
    }


def write_result(payload: Dict[str, object]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_summary(payload: Dict[str, object]) -> None:
    if SUMMARY_PATH is None:
        return
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SUMMARY_PATH.with_suffix(SUMMARY_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(SUMMARY_PATH)


def normalized_path_key(path: Path) -> str:
    try:
        normalized = str(path.resolve())
    except OSError:
        normalized = str(path.absolute())
    # Windows paths are case-insensitive in the supported deployment setup,
    # while Linux paths are not.  Lower-casing unconditionally would collapse
    # distinct A.jpg/a.jpg staging files on the ECS host.
    return normalized.casefold() if os.name == "nt" else normalized


def current_file_sha256(file_path: Path) -> Optional[str]:
    """Hash one bounded ordinary file without following a final symlink."""
    if file_path.is_symlink():
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(file_path, flags)
    except (OSError, ValueError):
        return None

    try:
        with os.fdopen(descriptor, "rb") as input_file:
            before = os.fstat(input_file.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size <= 0
                or before.st_size > MAX_FILE_BYTES
            ):
                return None
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = input_file.read(min(1024 * 1024, MAX_FILE_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    return None
                digest.update(chunk)
            after = os.fstat(input_file.fileno())
            if (
                total != before.st_size
                or after.st_size != before.st_size
                or getattr(after, "st_mtime_ns", None) != getattr(before, "st_mtime_ns", None)
            ):
                return None
            return digest.hexdigest()
    except OSError:
        return None


def archive_processed_file(file_path: Path, digest: str) -> Path:
    """Atomically leave the staging queue after a confirmed DB outcome."""
    expected = digest.lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise RuntimeError("cannot archive file with an invalid SHA256")
    if current_file_sha256(file_path) != expected:
        raise RuntimeError("staging file changed before it could be archived")
    if PROCESSED_DIR.is_symlink():
        raise RuntimeError("processed directory must not be a symbolic link")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if PROCESSED_DIR.is_symlink() or not PROCESSED_DIR.is_dir():
        raise RuntimeError("processed directory must be an ordinary directory")
    if file_path.stat().st_dev != PROCESSED_DIR.stat().st_dev:
        raise RuntimeError("staging and processed directories must share one filesystem")

    suffix = file_path.suffix.lower()
    target = PROCESSED_DIR / "{}{}".format(expected, suffix)
    if target.is_symlink():
        raise RuntimeError("processed target must not be a symbolic link")
    os.replace(file_path, target)
    if os.name == "posix":
        directory_fd = os.open(PROCESSED_DIR, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return target


def load_import_result_index() -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    if not RESUME_IMPORT_RESULTS or not RESULT_PATH.exists():
        return results
    with RESULT_PATH.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not row.get("ok") or not row.get("path"):
                continue
            results[normalized_path_key(Path(str(row["path"])))] = row
    return results


def already_imported_from_result(conn, file_path: Path, result_index: Dict[str, Dict[str, object]]) -> Optional[Dict[str, object]]:
    row = result_index.get(normalized_path_key(file_path))
    if not row:
        return None
    digest = str(row.get("hash") or "").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return None
    # A path is only a resume hint.  The operator may replace a same-named
    # staging file between runs, so verify the current bounded ordinary file
    # before trusting the historical path -> hash mapping.
    if current_file_sha256(file_path) != digest:
        return None
    existing = find_existing_image(conn, digest)
    if not existing:
        return None
    return {
        "ok": True,
        "status": "already-recorded",
        "path": str(file_path),
        "imageId": existing["image_id"],
        "hash": digest,
    }


def import_one(conn, client, author_id: int, file_path: Path) -> Dict[str, object]:
    file_size = file_path.stat().st_size
    if file_size <= 0 or file_size > MAX_FILE_BYTES:
        raise ValueError(
            "image file size {} is outside 1..{} bytes".format(file_size, MAX_FILE_BYTES)
        )
    data = file_path.read_bytes()
    if len(data) <= 0 or len(data) > MAX_FILE_BYTES:
        raise ValueError(
            "image payload size {} is outside 1..{} bytes".format(len(data), MAX_FILE_BYTES)
        )
    digest = sha256(data)
    existing = find_existing_image(conn, digest)
    if existing:
        return {
            "ok": True,
            "status": "duplicate",
            "path": str(file_path),
            "imageId": existing["image_id"],
            "hash": digest,
        }

    width, height, thumb_bytes, mime, suffix = read_image_info(data)
    original_key, thumb_key = object_keys(digest, suffix)
    put_object(client, original_key, data, mime)
    put_object(client, thumb_key, thumb_bytes, "image/jpeg")
    rows = insert_image_rows(
        conn,
        author_id,
        file_path,
        original_key,
        thumb_key,
        width,
        height,
        len(data),
        digest,
        mime,
    )
    return {
        "ok": True,
        "status": "imported-pending-review",
        "reviewStatus": "PENDING_REVIEW",
        "path": str(file_path),
        **rows,
    }


def run() -> None:
    files = image_files()
    if not files:
        summary = {
            "imported": 0,
            "pendingReview": 0,
            "duplicates": 0,
            "skipped": 0,
            "failed": 0,
            "attempted": 0,
            "limit": LIMIT,
            "resultPath": str(RESULT_PATH),
        }
        write_summary(summary)
        print("没有待导入图片；本次为空队列成功结束：{}".format(IMAGE_DIR))
        return

    if RESULT_PATH.exists() and not RESUME_IMPORT_RESULTS:
        RESULT_PATH.unlink()

    client = minio_client()
    ensure_bucket(client)
    imported = 0
    duplicates = 0
    skipped = 0
    failed = 0
    attempted = 0
    result_index = load_import_result_index()

    with connect_mysql() as conn:
        ensure_database_schema(conn)
        author_id = ensure_import_user(conn)
        conn.commit()
        for index, file_path in enumerate(files, start=1):
            print("[{}/{}] {}".format(index, len(files), file_path))
            try:
                result = already_imported_from_result(conn, file_path, result_index)
                if result:
                    archive_processed_file(file_path, str(result["hash"]))
                    skipped += 1
                    continue
                if attempted >= LIMIT:
                    break
                ensure_import_capacity()
                attempted += 1
                result = import_one(conn, client, author_id, file_path)
                conn.commit()
                archive_processed_file(file_path, str(result["hash"]))
                write_result(result)
                result_index[normalized_path_key(file_path)] = result
                if result["status"] == "duplicate":
                    duplicates += 1
                else:
                    imported += 1
            except Exception as exc:
                conn.rollback()
                failed += 1
                write_result({"ok": False, "path": str(file_path), "error": str(exc)})
                print("  失败：{}".format(exc), file=sys.stderr)
                if isinstance(exc, ImportCapacityError):
                    break

    summary = {
        "imported": imported,
        "pendingReview": imported,
        "duplicates": duplicates,
        "skipped": skipped,
        "failed": failed,
        "attempted": attempted,
        "limit": LIMIT,
        "resultPath": str(RESULT_PATH),
    }
    write_summary(summary)
    print("完成：新增={}，重复跳过={}，已记录跳过={}，失败={}，结果={}".format(
        imported,
        duplicates,
        skipped,
        failed,
        RESULT_PATH,
    ))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
