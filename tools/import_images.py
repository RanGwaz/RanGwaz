#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Development-only importer: local images -> MinIO + MySQL without calling publish APIs."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sys
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]

# Edit these constants in code when the local development environment changes.
IMAGE_DIR = ROOT / "tools" / "downloaded_dataset" / "images"
RESULT_PATH = ROOT / "tools" / "import_results.jsonl"
SCHEMA_PATH = ROOT / "backend" / "src" / "main" / "resources" / "db" / "schema.sql"
RECURSIVE = False
LIMIT = 0
AUTO_REBUILD_OLD_SCHEMA = True

IMPORT_USERNAME = "mira"
IMPORT_PASSWORD = "RanGwaz147.."
IMPORT_NICKNAME = "mira"
DEFAULT_IMAGE_CONTENT = "Imported image"
IMAGE_TITLE_PREFIX = ""

MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_DATABASE = "rangwaz_image_dev"
MYSQL_USER = "rangwaz"
MYSQL_PASSWORD = "rangwaz123"

MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_BUCKET = "rangwaz-media"
MINIO_SECURE = False
MEDIA_OBJECT_PREFIX = "/media/object"

THUMBNAIL_MAX_WIDTH = 520
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
PASSWORD_SALT = "rangwaz-local-dev"


_DEPS = None


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
            "缺少导入依赖，请先执行：python -m pip install pymysql minio pycryptodome pillow\n"
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
        client.make_bucket(MINIO_BUCKET)


def password_hash(raw: str) -> str:
    return hashlib.sha256((PASSWORD_SALT + ":" + raw).encode("utf-8")).hexdigest()


def ensure_import_user(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM app_users WHERE username=%s", (IMPORT_USERNAME,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE app_users SET password_hash=%s,nickname=%s,status='ACTIVE' WHERE id=%s",
                (password_hash(IMPORT_PASSWORD), IMPORT_NICKNAME, row["id"]),
            )
            return int(row["id"])
        cursor.execute(
            """
            INSERT INTO app_users(username,password_hash,nickname,status)
            VALUES(%s,%s,%s,'ACTIVE')
            """,
            (IMPORT_USERNAME, password_hash(IMPORT_PASSWORD), IMPORT_NICKNAME),
        )
        return int(cursor.lastrowid)


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


def run_schema(conn) -> None:
    if not SCHEMA_PATH.exists():
        raise SystemExit("找不到数据库结构文件：{}".format(SCHEMA_PATH))
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = []
    current = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).rstrip(";"))
            current = []
    if current:
        statements.append("\n".join(current))
    with conn.cursor() as cursor:
        for statement in statements:
            if statement.strip():
                cursor.execute(statement)
    conn.commit()


def ensure_database_schema(conn) -> None:
    needs_rebuild = (
        not table_exists(conn, "images")
        or not column_exists(conn, "images", "author_id")
        or table_exists(conn, "posts")
        or not table_exists(conn, "image_topics")
    )
    if not needs_rebuild:
        return
    if not AUTO_REBUILD_OLD_SCHEMA:
        raise SystemExit("当前数据库结构不是新版 images 单表结构，请先手动执行 {}".format(SCHEMA_PATH))
    print("检测到旧版或缺失的数据库结构，正在按新版 schema 重建开发库...")
    run_schema(conn)
    print("数据库结构已重建。")


def image_files() -> List[Path]:
    pattern = "**/*" if RECURSIVE else "*"
    files = [
        path
        for path in IMAGE_DIR.glob(pattern)
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    files = sorted(files)
    return files[:LIMIT] if LIMIT else files


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return guessed if guessed.startswith("image/") else "application/octet-stream"


def extension(path: Path, mime: str) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    if mime == "image/png":
        return ".png"
    if mime == "image/webp":
        return ".webp"
    if mime == "image/gif":
        return ".gif"
    return ".jpg"


def read_image_info(data: bytes) -> Tuple[int, int, bytes]:
    _, _, Image, ImageOps = require_dependencies()
    with Image.open(BytesIO(data)) as image:
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
        return width, height, output.getvalue()


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
            VALUES(%s,%s,%s,'image',NULL,%s,%s,'image',%s,%s,%s,%s,%s,%s,NULL,'PUBLISHED',
                   0,0,0,0,0,0,NOW())
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


def import_one(conn, client, author_id: int, file_path: Path) -> Dict[str, object]:
    data = file_path.read_bytes()
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

    mime = content_type(file_path)
    width, height, thumb_bytes = read_image_info(data)
    date_path = date.today().strftime("%Y/%m/%d")
    suffix = extension(file_path, mime)
    object_id = "{}-{}".format(digest[:20], uuid.uuid4().hex[:8])
    original_key = "originals/{}/{}{}".format(date_path, object_id, suffix)
    thumb_key = "thumbs/{}/{}.jpg".format(date_path, object_id)
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
    return {"ok": True, "status": "imported", "path": str(file_path), **rows}


def run() -> None:
    files = image_files()
    if not files:
        raise SystemExit("没有找到图片：{}".format(IMAGE_DIR))

    if RESULT_PATH.exists():
        RESULT_PATH.unlink()

    client = minio_client()
    ensure_bucket(client)
    imported = 0
    duplicates = 0
    failed = 0

    with connect_mysql() as conn:
        ensure_database_schema(conn)
        author_id = ensure_import_user(conn)
        conn.commit()
        for index, file_path in enumerate(files, start=1):
            print("[{}/{}] {}".format(index, len(files), file_path))
            try:
                result = import_one(conn, client, author_id, file_path)
                conn.commit()
                write_result(result)
                if result["status"] == "duplicate":
                    duplicates += 1
                else:
                    imported += 1
            except Exception as exc:
                conn.rollback()
                failed += 1
                write_result({"ok": False, "path": str(file_path), "error": str(exc)})
                print("  失败：{}".format(exc), file=sys.stderr)

    print("完成：新增={}，重复跳过={}，失败={}，结果={}".format(imported, duplicates, failed, RESULT_PATH))


if __name__ == "__main__":
    run()
