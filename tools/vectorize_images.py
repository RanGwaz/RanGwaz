#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local GPU vector worker: images -> visual embeddings -> Milvus + MySQL status."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "tools" / "models"

IMPORT_RESULTS_PATH = ROOT / "tools" / "import_results.jsonl"
IMAGE_DIR = ROOT / "tools" / "downloaded_dataset" / "images"
BACKEND_BASE_URL = "http://127.0.0.1:8080"

MYSQL_HOST = os.environ.get("VIBELO_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("VIBELO_MYSQL_PORT", "3306") or "3306")
MYSQL_DATABASE = os.environ.get("VIBELO_MYSQL_DATABASE", "rangwaz_image_dev")
MYSQL_USER = os.environ.get("VIBELO_MYSQL_USER", "rangwaz")
MYSQL_PASSWORD = os.environ.get("VIBELO_MYSQL_PASSWORD", "rangwaz123")

MILVUS_HOST = os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("VIBELO_MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("VIBELO_MILVUS_COLLECTION", "vibelo_image_vectors_siglip2_base_p224_d512")
VECTOR_FIELD = "embedding"

MODEL_NAME = os.environ.get("VIBELO_EMBED_MODEL", "google/siglip2-base-patch16-224")
VECTOR_VERSION = os.environ.get("VIBELO_EMBED_VECTOR_VERSION", "siglip2-base-p224-d512-v1")
VECTOR_DIMENSION = 512
PROJECTION_SEED = 20260606
DEVICE = os.environ.get("VIBELO_EMBED_DEVICE", "auto")
MODEL_TORCH_DTYPE = os.environ.get("VIBELO_EMBED_TORCH_DTYPE", "auto")
HF_CACHE_DIR = Path(os.environ.get("VIBELO_HF_HOME", str(MODELS_DIR / "huggingface")))
TORCH_CACHE_DIR = Path(os.environ.get("VIBELO_TORCH_HOME", str(MODELS_DIR / "torch")))
MODEL_LOCAL_DIR = HF_CACHE_DIR / MODEL_NAME.replace("/", "__")
MODEL_LOAD_PATH = os.environ.get(
    "VIBELO_EMBED_MODEL_PATH",
    str(MODEL_LOCAL_DIR) if MODEL_LOCAL_DIR.exists() else MODEL_NAME,
)

BATCH_SIZE = int(os.environ.get("VIBELO_EMBED_BATCH_SIZE", "4") or "4")
LIMIT = int(os.environ.get("VIBELO_EMBED_LIMIT", "0") or "0")
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 20

USE_HUGGINGFACE_PROXY = os.environ.get("VIBELO_USE_HF_PROXY", "0") == "1"
HUGGINGFACE_PROXY_URL = os.environ.get("VIBELO_HF_PROXY_URL", "http://127.0.0.1:12000")

if USE_HUGGINGFACE_PROXY:
    os.environ["HTTP_PROXY"] = HUGGINGFACE_PROXY_URL
    os.environ["HTTPS_PROXY"] = HUGGINGFACE_PROXY_URL
    os.environ["http_proxy"] = HUGGINGFACE_PROXY_URL
    os.environ["https_proxy"] = HUGGINGFACE_PROXY_URL
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(HF_CACHE_DIR / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_CACHE_DIR / "transformers"))
os.environ.setdefault("TORCH_HOME", str(TORCH_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(MODELS_DIR / "cache"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_PYMYSQL = None
_MILVUS = None
_PIL = None
_MODEL = None
_PROJECTION_MATRIX = None
_PROJECTION_INPUT_DIMENSION = None


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


def resolve_imported_image_path(raw_path: object) -> Optional[Path]:
    image_path = Path(str(raw_path or ""))
    if image_path.name:
        fallback = IMAGE_DIR / image_path.name
        if fallback.exists():
            return fallback
    if image_path.exists():
        return image_path
    return None


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


def require_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        import torch
        import transformers
        from transformers import AutoModel, AutoProcessor
    except ImportError as exc:
        raise SystemExit("Missing torch/transformers. Install tools/requirements_recommendation.txt first.") from exc
    version_parts = tuple(
        int(part)
        for part in transformers.__version__.split("+", 1)[0].split(".")[:2]
        if part.isdigit()
    )
    if version_parts < (4, 51):
        raise SystemExit(
            "transformers {} is too old for SigLIP2. Use the project venv instead:\n"
            "  .\\tools\\.venv\\Scripts\\python.exe tools\\vectorize_images.py\n"
            "Current Python:\n"
            "  {}".format(transformers.__version__, sys.executable)
        )

    if DEVICE == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = DEVICE
    model_kwargs = {}
    if device.startswith("cuda") and MODEL_TORCH_DTYPE == "auto":
        model_kwargs["torch_dtype"] = torch.float16
    elif MODEL_TORCH_DTYPE and MODEL_TORCH_DTYPE != "auto":
        model_kwargs["torch_dtype"] = getattr(torch, MODEL_TORCH_DTYPE)
    processor = AutoProcessor.from_pretrained(MODEL_LOAD_PATH)
    model = AutoModel.from_pretrained(MODEL_LOAD_PATH, **model_kwargs)
    model.to(device)
    model.eval()
    _MODEL = (torch, processor, model, device)
    return _MODEL


def as_feature_tensor(torch, value):
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
            tensor = as_feature_tensor(torch, item)
            if torch.is_tensor(tensor):
                return tensor
    raise RuntimeError("model did not return an image feature tensor: {}".format(type(value).__name__))


def l2_normalize(features):
    return features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)


def projection_matrix(torch, input_dimension: int, device: str):
    global _PROJECTION_MATRIX, _PROJECTION_INPUT_DIMENSION
    if input_dimension == VECTOR_DIMENSION:
        return None
    if input_dimension < VECTOR_DIMENSION:
        raise RuntimeError("Model vector dimension {} is smaller than configured {}".format(
            input_dimension,
            VECTOR_DIMENSION,
        ))
    if _PROJECTION_MATRIX is None or _PROJECTION_INPUT_DIMENSION != input_dimension:
        generator = torch.Generator()
        generator.manual_seed(PROJECTION_SEED)
        matrix = torch.randn(
            (input_dimension, VECTOR_DIMENSION),
            generator=generator,
            dtype=torch.float32,
        ) / (VECTOR_DIMENSION ** 0.5)
        _PROJECTION_MATRIX = matrix.to(device)
        _PROJECTION_INPUT_DIMENSION = input_dimension
    return _PROJECTION_MATRIX


def project_features(torch, features, device: str):
    features = l2_normalize(features.float())
    matrix = projection_matrix(torch, int(features.shape[-1]), device)
    if matrix is None:
        return l2_normalize(features)
    return l2_normalize(features @ matrix)


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
            path = resolve_imported_image_path(row["path"])
            if path:
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


def encode_images(images):
    torch, processor, model, device = require_model()
    try:
        inputs = processor(images=images, return_tensors="pt", padding=True)
    except TypeError:
        inputs = processor(images=images, return_tensors="pt")
    model_dtype = next(model.parameters()).dtype
    inputs = {
        key: value.to(device, dtype=model_dtype) if torch.is_floating_point(value) else value.to(device)
        for key, value in inputs.items()
    }
    with torch.no_grad():
        if hasattr(model, "get_image_features"):
            features = as_feature_tensor(torch, model.get_image_features(**inputs))
        else:
            outputs = model.vision_model(pixel_values=inputs["pixel_values"])
            features = as_feature_tensor(torch, outputs)
            projection = getattr(model, "visual_projection", None) or getattr(model, "vision_projection", None)
            if projection is not None:
                features = projection(features)
        features = project_features(torch, features, device)
    vectors = features.detach().float().cpu().numpy().astype("float32")
    if vectors.shape[1] != VECTOR_DIMENSION:
        raise RuntimeError("Model vector dimension {} does not match configured {}".format(vectors.shape[1], VECTOR_DIMENSION))
    return vectors


def upsert_vectors(collection, rows: Sequence[ImageRow], vectors) -> None:
    vector_list = [vector.tolist() for vector in vectors]
    payload = [
        [row.image_id for row in rows],
        vector_list,
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
    print("Loading embedding model {} from {} with proxy {}.".format(
        MODEL_NAME,
        MODEL_LOAD_PATH,
        HUGGINGFACE_PROXY_URL if USE_HUGGINGFACE_PROXY else "disabled",
    ))
    require_model()
    local_paths = import_path_map()
    collection = ensure_collection()
    ok = 0
    failed = 0
    consecutive_failed = 0
    with connect_mysql() as conn:
        rows = pending_images(conn)
        print("Vectorizing {} images into Milvus collection {}.".format(len(rows), MILVUS_COLLECTION))
        for batch_index, batch in enumerate(chunks(rows, BATCH_SIZE), start=1):
            print("[batch {}] image {}..{}".format(batch_index, batch[0].image_id, batch[-1].image_id))
            valid_rows: List[ImageRow] = []
            images = []
            for row in batch:
                try:
                    images.append(open_image(row, local_paths))
                    valid_rows.append(row)
                except Exception as exc:
                    failed += 1
                    consecutive_failed += 1
                    mark_failed(conn, row, exc)
                    print("  failed load image {}: {}".format(row.image_id, exc), file=sys.stderr)
            if not valid_rows:
                if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                    raise SystemExit("Too many consecutive failures; stop vector worker.")
                continue
            try:
                mark_processing(conn, valid_rows)
                vectors = encode_images(images)
                upsert_vectors(collection, valid_rows, vectors)
                mark_ready(conn, valid_rows)
                ok += len(valid_rows)
                consecutive_failed = 0
            except Exception as exc:
                failed += len(valid_rows)
                consecutive_failed += len(valid_rows)
                for row in valid_rows:
                    mark_failed(conn, row, exc)
                print("  failed vector batch: {}".format(exc), file=sys.stderr)
                if consecutive_failed >= MAX_CONSECUTIVE_FAILURES:
                    raise SystemExit("Too many consecutive failures; stop vector worker.") from exc
            finally:
                for image in images:
                    try:
                        image.close()
                    except Exception:
                        pass
    print("Done. embedded={}, failed={}".format(ok, failed))


if __name__ == "__main__":
    start = time.time()
    run()
    print("Elapsed {:.0f}s".format(time.time() - start))
