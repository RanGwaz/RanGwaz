#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local vector worker: local images -> remote GPU embeddings -> local Milvus/MySQL."""

from __future__ import annotations

import base64
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parents[1]

IMPORT_RESULTS_PATH = ROOT / "tools" / "import_results.jsonl"
BACKEND_BASE_URL = "http://127.0.0.1:8080"

MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_DATABASE = "rangwaz_image_dev"
MYSQL_USER = "rangwaz"
MYSQL_PASSWORD = "rangwaz123"

MILVUS_HOST = "127.0.0.1"
MILVUS_PORT = "19530"
MILVUS_COLLECTION = "vibelo_image_vectors_siglip2_giant_p384_d512"
VECTOR_FIELD = "embedding"

MODEL_NAME = "google/siglip2-giant-opt-patch16-384"
VECTOR_VERSION = "siglip2-giant-p384-d512-v1"
VECTOR_DIMENSION = 512

REMOTE_EMBEDDING_URL = "https://uu1040521-ba3c-2fe32904.westb.seetacloud.com:8443"
REMOTE_EMBEDDING_API_KEY = "VibeloGPU_20260606_SigLIP2"
USE_REMOTE_API_PROXY = True
REMOTE_API_PROXY_URL = "http://127.0.0.1:12000"

BATCH_SIZE = 16
LIMIT = 0
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
REMOTE_TIMEOUT_SECONDS = 240
MAX_CONSECUTIVE_FAILURES = 20
MODEL_IMAGE_MAX_SIDE = 384
MODEL_IMAGE_JPEG_QUALITY = 85
LOCAL_IMAGE_WORKERS = 8
MILVUS_FLUSH_EVERY_BATCHES = 10
MAX_REMOTE_RETRIES = 3
REMOTE_RETRY_BASE_SECONDS = 3

_PYMYSQL = None
_MILVUS = None
_PIL = None
_OPENER = build_opener(ProxyHandler({
    "http": REMOTE_API_PROXY_URL,
    "https": REMOTE_API_PROXY_URL,
}) if USE_REMOTE_API_PROXY else ProxyHandler({}))


@dataclass(frozen=True)
class ImageRow:
    image_id: int
    file_url: str
    thumbnail_url: str
    width: int
    height: int
    image_hash: str
    main_category_id: int
    published_at_epoch: int


@dataclass(frozen=True)
class PreparedImage:
    row: ImageRow
    encoded_image: str


def require_pymysql():
    global _PYMYSQL
    if _PYMYSQL is None:
        try:
            import pymysql
        except ImportError as exc:
            raise SystemExit("Missing pymysql. Install tools/requirements_recommendation.txt first.") from exc
        _PYMYSQL = pymysql
    return _PYMYSQL


def require_milvus():
    global _MILVUS
    if _MILVUS is None:
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
        except ImportError as exc:
            raise SystemExit("Missing pymilvus. Install tools/requirements_recommendation.txt first.") from exc
        _MILVUS = (Collection, CollectionSchema, DataType, FieldSchema, connections, utility)
    return _MILVUS


def require_pillow():
    global _PIL
    if _PIL is None:
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise SystemExit("Missing Pillow. Install tools/requirements_recommendation.txt first.") from exc
        _PIL = (Image, ImageOps)
    return _PIL


def connect_mysql():
    pymysql = require_pymysql()
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def ensure_collection():
    Collection, CollectionSchema, DataType, FieldSchema, connections, utility = require_milvus()
    connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
    if not utility.has_collection(MILVUS_COLLECTION):
        fields = [
            FieldSchema(name="image_id", dtype=DataType.INT64, is_primary=True, auto_id=False),
            FieldSchema(name=VECTOR_FIELD, dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIMENSION),
            FieldSchema(name="image_hash", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="width", dtype=DataType.INT64),
            FieldSchema(name="height", dtype=DataType.INT64),
            FieldSchema(name="main_category_id", dtype=DataType.INT64),
            FieldSchema(name="published_at", dtype=DataType.INT64),
        ]
        schema = CollectionSchema(fields=fields, description="Vibelo image embedding vectors")
        collection = Collection(name=MILVUS_COLLECTION, schema=schema)
        collection.create_index(
            field_name=VECTOR_FIELD,
            index_params={
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 32, "efConstruction": 200},
            },
        )
    else:
        collection = Collection(MILVUS_COLLECTION)
    collection.load()
    return collection


def import_path_map() -> Dict[int, Path]:
    result: Dict[int, Path] = {}
    if not IMPORT_RESULTS_PATH.exists():
        return result
    with IMPORT_RESULTS_PATH.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not row.get("ok") or not row.get("imageId") or not row.get("path"):
                continue
            path = Path(str(row["path"]))
            if path.exists():
                result[int(row["imageId"])] = path
    return result


def pending_images(conn) -> List[ImageRow]:
    sql = """
        SELECT i.id,
               i.file_url,
               i.thumbnail_url,
               COALESCE(i.width,0) AS width,
               COALESCE(i.height,0) AS height,
               COALESCE(i.hash,'') AS image_hash,
               COALESCE(i.main_category_id,0) AS main_category_id,
               UNIX_TIMESTAMP(COALESCE(i.published_at,i.created_at,NOW())) AS published_at_epoch
        FROM images i
        LEFT JOIN image_embeddings e
          ON e.image_id=i.id
         AND e.model_name=%s
         AND e.vector_version=%s
        WHERE i.status='PUBLISHED'
          AND (
            e.image_id IS NULL
            OR e.status <> 'READY'
            OR COALESCE(e.image_hash,'') <> COALESCE(i.hash,'')
          )
        ORDER BY i.id
    """
    if LIMIT and LIMIT > 0:
        sql += " LIMIT {}".format(int(LIMIT))
    with conn.cursor() as cursor:
        cursor.execute(sql, (MODEL_NAME, VECTOR_VERSION))
        rows = cursor.fetchall()
    return [
        ImageRow(
            image_id=int(row["id"]),
            file_url=str(row.get("file_url") or ""),
            thumbnail_url=str(row.get("thumbnail_url") or ""),
            width=int(row.get("width") or 0),
            height=int(row.get("height") or 0),
            image_hash=str(row.get("image_hash") or ""),
            main_category_id=int(row.get("main_category_id") or 0),
            published_at_epoch=int(row.get("published_at_epoch") or 0),
        )
        for row in rows
    ]


def chunks(items: Sequence[ImageRow], size: int) -> Iterable[List[ImageRow]]:
    for index in range(0, len(items), size):
        yield list(items[index:index + size])


def mark_processing(conn, rows: Sequence[ImageRow]) -> None:
    with conn.cursor() as cursor:
        for row in rows:
            cursor.execute(
                """
                INSERT INTO image_embeddings(image_id,model_name,vector_version,vector_dimension,image_hash,milvus_collection,milvus_pk,status,last_error)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'PROCESSING',NULL)
                ON DUPLICATE KEY UPDATE
                  vector_dimension=VALUES(vector_dimension),
                  image_hash=VALUES(image_hash),
                  milvus_collection=VALUES(milvus_collection),
                  milvus_pk=VALUES(milvus_pk),
                  status='PROCESSING',
                  last_error=NULL
                """,
                (row.image_id, MODEL_NAME, VECTOR_VERSION, VECTOR_DIMENSION, row.image_hash, MILVUS_COLLECTION, row.image_id),
            )
    conn.commit()


def mark_ready(conn, rows: Sequence[ImageRow]) -> None:
    with conn.cursor() as cursor:
        for row in rows:
            cursor.execute(
                """
                UPDATE image_embeddings
                SET status='READY',
                    last_error=NULL,
                    embedded_at=NOW(),
                    updated_at=NOW()
                WHERE image_id=%s AND model_name=%s AND vector_version=%s
                """,
                (row.image_id, MODEL_NAME, VECTOR_VERSION),
            )
    conn.commit()


def mark_failed(conn, row: ImageRow, error: BaseException) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO image_embeddings(image_id,model_name,vector_version,vector_dimension,image_hash,milvus_collection,milvus_pk,status,last_error)
            VALUES(%s,%s,%s,%s,%s,%s,%s,'FAILED',%s)
            ON DUPLICATE KEY UPDATE
              status='FAILED',
              last_error=VALUES(last_error),
              updated_at=NOW()
            """,
            (
                row.image_id,
                MODEL_NAME,
                VECTOR_VERSION,
                VECTOR_DIMENSION,
                row.image_hash,
                MILVUS_COLLECTION,
                row.image_id,
                str(error)[:500],
            ),
        )
    conn.commit()


def open_image(row: ImageRow, local_paths: Dict[int, Path]):
    Image, ImageOps = require_pillow()
    path = local_paths.get(row.image_id)
    if path and path.exists():
        image = Image.open(path)
    else:
        url = row.file_url or row.thumbnail_url
        if url.startswith("/"):
            url = urljoin(BACKEND_BASE_URL.rstrip("/") + "/", url.lstrip("/"))
        with urlopen(url, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS) as response:
            image = Image.open(io.BytesIO(response.read()))
    return ImageOps.exif_transpose(image).convert("RGB")


def encode_image(image) -> str:
    Image, _ = require_pillow()
    copy = image.copy()
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    copy.thumbnail((MODEL_IMAGE_MAX_SIDE, MODEL_IMAGE_MAX_SIDE), resampling)
    if copy.mode != "RGB":
        copy = copy.convert("RGB")
    output = io.BytesIO()
    copy.save(output, format="JPEG", quality=MODEL_IMAGE_JPEG_QUALITY, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def prepare_image(row: ImageRow, local_paths: Dict[int, Path]) -> PreparedImage:
    image = open_image(row, local_paths)
    try:
        encoded = encode_image(image)
        return PreparedImage(row=row, encoded_image=encoded)
    finally:
        try:
            image.close()
        except Exception:
            pass


def prepare_batch(rows: Sequence[ImageRow], local_paths: Dict[int, Path], conn) -> List[PreparedImage]:
    prepared: List[PreparedImage] = []
    worker_count = min(LOCAL_IMAGE_WORKERS, max(1, len(rows)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(prepare_image, row, local_paths): row for row in rows}
        for future in as_completed(future_map):
            row = future_map[future]
            try:
                prepared.append(future.result())
            except Exception as exc:
                mark_failed(conn, row, exc)
                print("  failed prepare image {}: {}".format(row.image_id, exc), file=sys.stderr)
    prepared.sort(key=lambda item: item.row.image_id)
    return prepared


def remote_post(path: str, payload: Dict[str, object]) -> Dict[str, object]:
    request = Request(
        urljoin(REMOTE_EMBEDDING_URL.rstrip("/") + "/", path.lstrip("/")),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(REMOTE_EMBEDDING_API_KEY),
        },
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=REMOTE_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("remote HTTP {}: {}".format(exc.code, body[:1000])) from exc
    except URLError as exc:
        raise RuntimeError("remote URL error: {}".format(exc.reason)) from exc


def remote_get(path: str) -> Dict[str, object]:
    request = Request(
        urljoin(REMOTE_EMBEDDING_URL.rstrip("/") + "/", path.lstrip("/")),
        headers={"Authorization": "Bearer {}".format(REMOTE_EMBEDDING_API_KEY)},
        method="GET",
    )
    try:
        with _OPENER.open(request, timeout=REMOTE_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("remote HTTP {}: {}".format(exc.code, body[:1000])) from exc


def check_remote_service() -> None:
    health = remote_get("/health")
    dimension = int(health.get("dimension") or 0)
    if dimension != VECTOR_DIMENSION:
        raise RuntimeError("remote dimension {} does not match {}".format(dimension, VECTOR_DIMENSION))
    print("Remote embedding service OK: {}".format(json.dumps(health, ensure_ascii=False)))


def encode_prepared_remote(prepared: Sequence[PreparedImage]) -> tuple[List[List[float]], Dict[str, float]]:
    payload = {"images": [item.encoded_image for item in prepared]}
    payload_size_mb = len(json.dumps(payload).encode("utf-8")) / 1024 / 1024
    result = None
    last_error: BaseException | None = None
    for attempt in range(1, MAX_REMOTE_RETRIES + 1):
        try:
            started_at = time.perf_counter()
            result = remote_post("/embed", payload)
            elapsed = time.perf_counter() - started_at
            timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
            timings = {str(key): float(value) for key, value in timings.items() if isinstance(value, (int, float))}
            timings["request"] = round(elapsed, 4)
            timings["payloadMb"] = round(payload_size_mb, 3)
            break
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_REMOTE_RETRIES:
                raise
            wait_seconds = REMOTE_RETRY_BASE_SECONDS * attempt
            print("  remote call failed, retry {}/{} after {}s: {}".format(
                attempt,
                MAX_REMOTE_RETRIES,
                wait_seconds,
                exc,
            ), file=sys.stderr)
            time.sleep(wait_seconds)
    if result is None:
        raise RuntimeError("remote request failed: {}".format(last_error))
    vectors = result.get("vectors")
    if not isinstance(vectors, list):
        raise RuntimeError("remote response missing vectors")
    if len(vectors) != len(prepared):
        raise RuntimeError("remote returned {} vectors for {} images".format(len(vectors), len(prepared)))
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != VECTOR_DIMENSION:
            raise RuntimeError("bad vector dimension from remote")
    return vectors, timings


def upsert_vectors(collection, rows: Sequence[ImageRow], vectors: Sequence[Sequence[float]]) -> None:
    payload = [
        [row.image_id for row in rows],
        [list(vector) for vector in vectors],
        [row.image_hash for row in rows],
        [row.width for row in rows],
        [row.height for row in rows],
        [row.main_category_id for row in rows],
        [row.published_at_epoch for row in rows],
    ]
    if hasattr(collection, "upsert"):
        collection.upsert(payload)
    else:
        ids = ",".join(str(row.image_id) for row in rows)
        collection.delete("image_id in [{}]".format(ids))
        collection.insert(payload)
    collection.flush()


def run() -> None:
    check_remote_service()
    local_paths = import_path_map()
    collection = ensure_collection()
    ok = 0
    failed = 0
    consecutive_failed = 0
    total_started_at = time.perf_counter()
    with connect_mysql() as conn:
        rows = pending_images(conn)
        print("Vectorizing {} images into Milvus collection {}.".format(len(rows), MILVUS_COLLECTION))
        for batch_index, batch in enumerate(chunks(rows, BATCH_SIZE), start=1):
            batch_started_at = time.perf_counter()
            print("[batch {}] image {}..{}".format(batch_index, batch[0].image_id, batch[-1].image_id))
            prepare_started_at = time.perf_counter()
            prepared = prepare_batch(batch, local_paths, conn)
            prepare_elapsed = time.perf_counter() - prepare_started_at
            failed_prepare_count = len(batch) - len(prepared)
            if failed_prepare_count:
                failed += failed_prepare_count
                consecutive_failed += failed_prepare_count
            valid_rows = [item.row for item in prepared]
            if not valid_rows:
                if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                    raise SystemExit("Too many consecutive failures; stop vector worker.")
                continue
            try:
                db_started_at = time.perf_counter()
                mark_processing(conn, valid_rows)
                processing_db_elapsed = time.perf_counter() - db_started_at
                remote_started_at = time.perf_counter()
                vectors, remote_timings = encode_prepared_remote(prepared)
                remote_elapsed = time.perf_counter() - remote_started_at
                milvus_started_at = time.perf_counter()
                upsert_vectors(collection, valid_rows, vectors)
                milvus_elapsed = time.perf_counter() - milvus_started_at
                ready_db_started_at = time.perf_counter()
                mark_ready(conn, valid_rows)
                ready_db_elapsed = time.perf_counter() - ready_db_started_at
                ok += len(valid_rows)
                consecutive_failed = 0
                batch_elapsed = time.perf_counter() - batch_started_at
                speed = len(valid_rows) / batch_elapsed if batch_elapsed > 0 else 0
                print(
                    "  ok={} prepare={:.1f}s remote={:.1f}s milvus={:.1f}s db={:.1f}s total={:.1f}s speed={:.2f}/s remoteParts={}".format(
                        len(valid_rows),
                        prepare_elapsed,
                        remote_elapsed,
                        milvus_elapsed,
                        processing_db_elapsed + ready_db_elapsed,
                        batch_elapsed,
                        speed,
                        json.dumps(remote_timings, ensure_ascii=False),
                    )
                )
            except Exception as exc:
                failed += len(valid_rows)
                consecutive_failed += len(valid_rows)
                for row in valid_rows:
                    mark_failed(conn, row, exc)
                print("  failed vector batch: {}".format(exc), file=sys.stderr)
                if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                    raise SystemExit("Too many consecutive failures; stop vector worker.") from exc
    elapsed = time.perf_counter() - total_started_at
    print("Done. embedded={}, failed={}, elapsed={:.0f}s, speed={:.2f}/s".format(
        ok,
        failed,
        elapsed,
        ok / elapsed if elapsed > 0 else 0,
    ))


if __name__ == "__main__":
    start = time.time()
    run()
    print("Elapsed {:.0f}s".format(time.time() - start))
