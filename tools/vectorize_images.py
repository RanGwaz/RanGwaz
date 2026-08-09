#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local GPU vector worker: images -> visual embeddings -> Milvus + MySQL status."""

from __future__ import annotations

import io
import hashlib
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
BACKEND_BASE_URL = os.environ.get("VIBELO_BACKEND_BASE_URL", "http://127.0.0.1")


def env_value(primary: str, fallback: str, default: str = "") -> str:
    return os.environ.get(primary) or os.environ.get(fallback) or default


MYSQL_HOST = env_value("VIBELO_DB_HOST", "VIBELO_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(env_value("VIBELO_DB_PORT", "VIBELO_MYSQL_PORT", "3306"))
MYSQL_DATABASE = env_value("VIBELO_DB_NAME", "VIBELO_MYSQL_DATABASE", "rangwaz_image_dev")
MYSQL_USER = env_value("VIBELO_DB_USER", "VIBELO_MYSQL_USER", "vibelo_app")
MYSQL_PASSWORD = env_value("VIBELO_DB_PASSWORD", "VIBELO_MYSQL_PASSWORD", "")

MILVUS_HOST = os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.environ.get("VIBELO_MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.environ.get("VIBELO_MILVUS_COLLECTION", "vibelo_image_vectors_siglip2_base_p224_d512")
VECTOR_FIELD = "embedding"

MODEL_NAME = os.environ.get("VIBELO_EMBED_MODEL", "google/siglip2-base-patch16-224")
VECTOR_VERSION = os.environ.get("VIBELO_EMBED_VECTOR_VERSION", "siglip2-base-p224-d512-v1")
VECTOR_DIMENSION = 512
PROJECTION_SEED = 20260606
SUPPORTED_PROJECTION_VERSION = "siglip-image-feature-l2-rp512-seed20260606-v1"
PROJECTION_VERSION = os.environ.get(
    "VIBELO_EMBED_PROJECTION_VERSION", SUPPORTED_PROJECTION_VERSION
)
if PROJECTION_VERSION != SUPPORTED_PROJECTION_VERSION:
    raise SystemExit("VIBELO_EMBED_PROJECTION_VERSION does not match this vector worker")
DEVICE = os.environ.get("VIBELO_EMBED_DEVICE", "auto")
MODEL_TORCH_DTYPE = os.environ.get("VIBELO_EMBED_TORCH_DTYPE", "auto")
MODEL_CACHE_ROOT = Path(os.environ.get("MODEL_CACHE_ROOT", str(MODELS_DIR)))
HF_CACHE_DIR = Path(os.environ.get("VIBELO_HF_HOME", str(MODEL_CACHE_ROOT / "huggingface")))
TORCH_CACHE_DIR = Path(
    os.environ.get("TORCH_HOME")
    or os.environ.get("VIBELO_TORCH_HOME")
    or str(MODEL_CACHE_ROOT / "torch")
)
XDG_CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME")
    or os.environ.get("XDG_CACHE")
    or str(MODEL_CACHE_ROOT / "xdg")
)
MODEL_LOCAL_DIR = HF_CACHE_DIR / MODEL_NAME.replace("/", "__")
MODEL_LOAD_PATH = os.environ.get(
    "VIBELO_EMBED_MODEL_PATH",
    str(MODEL_LOCAL_DIR) if MODEL_LOCAL_DIR.exists() else MODEL_NAME,
)
OFFLINE_MODE = os.environ.get("VIBELO_MODEL_OFFLINE", "0") == "1"
REQUIRE_DATA_CACHE = os.environ.get("VIBELO_REQUIRE_DATA_CACHE", "0") == "1"

BATCH_SIZE = int(os.environ.get("VIBELO_EMBED_BATCH_SIZE", "4") or "4")
LIMIT = int(os.environ.get("VIBELO_EMBED_LIMIT", "0") or "0")
REQUIRE_INDEX_COUNT_MATCH = os.environ.get("VIBELO_EMBED_REQUIRE_INDEX_COUNT_MATCH", "1") == "1"
READY_MARKER_PATH = (
    Path(os.environ["VIBELO_VECTOR_READY_MARKER"])
    if os.environ.get("VIBELO_VECTOR_READY_MARKER")
    else None
)
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 20

USE_HUGGINGFACE_PROXY = os.environ.get("VIBELO_USE_HF_PROXY", "0") == "1"
HUGGINGFACE_PROXY_URL = os.environ.get("VIBELO_HF_PROXY_URL", "http://127.0.0.1:12000")

if OFFLINE_MODE and USE_HUGGINGFACE_PROXY:
    raise SystemExit("Offline model mode cannot be combined with a Hugging Face proxy.")

if USE_HUGGINGFACE_PROXY:
    os.environ["HTTP_PROXY"] = HUGGINGFACE_PROXY_URL
    os.environ["HTTPS_PROXY"] = HUGGINGFACE_PROXY_URL
    os.environ["http_proxy"] = HUGGINGFACE_PROXY_URL
    os.environ["https_proxy"] = HUGGINGFACE_PROXY_URL
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ["HF_HOME"] = str(HF_CACHE_DIR)
os.environ["HF_HUB_CACHE"] = str(HF_CACHE_DIR / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(HF_CACHE_DIR / "transformers")
os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
os.environ["XDG_CACHE_HOME"] = str(XDG_CACHE_DIR)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
if OFFLINE_MODE:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"


def _is_under_data(path: Path) -> bool:
    data_root = Path("/data").resolve(strict=False)
    resolved = path.resolve(strict=False)
    return resolved == data_root or data_root in resolved.parents


if REQUIRE_DATA_CACHE:
    for cache_name, cache_path in (
        ("MODEL_CACHE_ROOT", MODEL_CACHE_ROOT),
        ("VIBELO_HF_HOME", HF_CACHE_DIR),
        ("TORCH_HOME", TORCH_CACHE_DIR),
        ("XDG_CACHE_HOME", XDG_CACHE_DIR),
    ):
        if not _is_under_data(cache_path):
            raise SystemExit("{} must resolve below /data: {}".format(cache_name, cache_path))

MODEL_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
XDG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
    processor = AutoProcessor.from_pretrained(MODEL_LOAD_PATH, local_files_only=OFFLINE_MODE)
    model = AutoModel.from_pretrained(MODEL_LOAD_PATH, local_files_only=OFFLINE_MODE, **model_kwargs)
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
        validate_collection(collection)
    collection.load()
    return collection


def validate_collection(collection) -> None:
    """Fail closed when an existing collection cannot hold this vector artifact."""
    vector_field = next((field for field in collection.schema.fields if field.name == VECTOR_FIELD), None)
    if vector_field is None:
        raise RuntimeError("Milvus collection {} has no {} field".format(MILVUS_COLLECTION, VECTOR_FIELD))
    dimension = int((getattr(vector_field, "params", {}) or {}).get("dim", 0) or 0)
    if dimension != VECTOR_DIMENSION:
        raise RuntimeError(
            "Milvus collection {} dimension {} does not match {}".format(
                MILVUS_COLLECTION,
                dimension,
                VECTOR_DIMENSION,
            )
        )
    vector_indexes = [
        index
        for index in (getattr(collection, "indexes", []) or [])
        if getattr(index, "field_name", None) == VECTOR_FIELD
    ]
    if len(vector_indexes) != 1:
        raise RuntimeError(
            "Milvus collection {} must have exactly one {} index".format(MILVUS_COLLECTION, VECTOR_FIELD)
        )
    params = getattr(vector_indexes[0], "params", {}) or {}
    metric = str(params.get("metric_type") or "").upper()
    index_type = str(params.get("index_type") or "").upper()
    if metric != "COSINE" or index_type != "HNSW":
        raise RuntimeError(
            "Milvus collection {} index must be HNSW/COSINE, got {}/{}".format(
                MILVUS_COLLECTION,
                index_type or "missing",
                metric or "missing",
            )
        )


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
         AND e.milvus_collection=%s
         AND e.vector_dimension=%s
        WHERE i.status='PUBLISHED'
          AND (
            e.image_id IS NULL
            OR e.status <> 'READY'
            OR COALESCE(e.image_hash,'') <> COALESCE(i.hash,'')
            OR COALESCE(e.milvus_pk,0) <> i.id
          )
        ORDER BY i.id
    """
    if LIMIT and LIMIT > 0:
        sql += " LIMIT {}".format(int(LIMIT))
    with conn.cursor() as cursor:
        cursor.execute(sql, (MODEL_NAME, VECTOR_VERSION, MILVUS_COLLECTION, VECTOR_DIMENSION))
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


def ready_embedding_count(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM image_embeddings e
            JOIN images i ON i.id=e.image_id AND i.status='PUBLISHED'
            WHERE e.model_name=%s
              AND e.vector_version=%s
              AND e.milvus_collection=%s
              AND e.vector_dimension=%s
              AND e.status='READY'
              AND COALESCE(e.image_hash,'')=COALESCE(i.hash,'')
              AND COALESCE(e.milvus_pk,0)=i.id
            """,
            (MODEL_NAME, VECTOR_VERSION, MILVUS_COLLECTION, VECTOR_DIMENSION),
        )
        return int(cursor.fetchone()["total"])


def pending_embedding_count(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM images i
            LEFT JOIN image_embeddings e
              ON e.image_id=i.id
             AND e.model_name=%s
             AND e.vector_version=%s
             AND e.milvus_collection=%s
             AND e.vector_dimension=%s
            WHERE i.status='PUBLISHED'
              AND (
                e.image_id IS NULL
                OR e.status<>'READY'
                OR COALESCE(e.image_hash,'')<>COALESCE(i.hash,'')
                OR COALESCE(e.milvus_pk,0)<>i.id
              )
            """,
            (MODEL_NAME, VECTOR_VERSION, MILVUS_COLLECTION, VECTOR_DIMENSION),
        )
        return int(cursor.fetchone()["total"])


def ready_embedding_ids(conn) -> set[int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.id
            FROM image_embeddings e
            JOIN images i ON i.id=e.image_id AND i.status='PUBLISHED'
            WHERE e.model_name=%s
              AND e.vector_version=%s
              AND e.milvus_collection=%s
              AND e.vector_dimension=%s
              AND e.status='READY'
              AND COALESCE(e.image_hash,'')=COALESCE(i.hash,'')
              AND COALESCE(e.milvus_pk,0)=i.id
            """,
            (MODEL_NAME, VECTOR_VERSION, MILVUS_COLLECTION, VECTOR_DIMENSION),
        )
        return {int(row["id"]) for row in cursor.fetchall()}


def collection_image_ids(collection) -> set[int]:
    result: set[int] = set()
    iterator = collection.query_iterator(
        batch_size=4096,
        expr="image_id > 0",
        output_fields=["image_id"],
    )
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            for row in batch:
                image_id = int(row.get("image_id") or 0)
                if image_id <= 0 or image_id in result:
                    raise RuntimeError("Milvus collection contains an invalid or duplicate image_id")
                result.add(image_id)
    finally:
        iterator.close()
    return result


def id_set_sha256(image_ids: set[int]) -> str:
    digest = hashlib.sha256()
    for image_id in sorted(image_ids):
        digest.update(str(image_id).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def assert_collection_model_binding(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT model_name,vector_version
            FROM image_embeddings
            WHERE milvus_collection=%s
              AND status='READY'
              AND (model_name<>%s OR vector_version<>%s)
            LIMIT 1
            """,
            (MILVUS_COLLECTION, MODEL_NAME, VECTOR_VERSION),
        )
        conflict = cursor.fetchone()
    if conflict:
        raise RuntimeError(
            "Milvus collection {} is already bound to {}/{}; use a new collection for {}/{}".format(
                MILVUS_COLLECTION,
                conflict["model_name"],
                conflict["vector_version"],
                MODEL_NAME,
                VECTOR_VERSION,
            )
        )


def remove_ready_marker() -> None:
    if READY_MARKER_PATH is not None:
        READY_MARKER_PATH.unlink(missing_ok=True)


def write_ready_marker(image_ids: set[int]) -> None:
    if READY_MARKER_PATH is None:
        return
    READY_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = READY_MARKER_PATH.with_name(READY_MARKER_PATH.name + ".tmp")
    payload = {
        "collection": MILVUS_COLLECTION,
        "dimension": VECTOR_DIMENSION,
        "entities": len(image_ids),
        "idSetSha256": id_set_sha256(image_ids),
        "metric": "COSINE",
        "model": MODEL_NAME,
        "projectionVersion": PROJECTION_VERSION,
        "ready": len(image_ids),
        "vectorVersion": VECTOR_VERSION,
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, READY_MARKER_PATH)


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
        assert_collection_model_binding(conn)
        ready_count = ready_embedding_count(conn)
        pending_count = pending_embedding_count(conn)
        entity_count = int(collection.num_entities)
        # A previous full-coverage marker is no longer sufficient once this run
        # observes new or stale work. It is recreated only after exact coverage.
        if pending_count > 0 or entity_count != ready_count:
            remove_ready_marker()
        if entity_count == 0 and ready_count > 0:
            raise SystemExit(
                "RDS marks {} embeddings READY but Milvus collection is empty. "
                "Publish a new vector version into a new collection instead of trusting stale status.".format(ready_count)
            )
        recoverable_upper_bound = ready_count + pending_count
        if REQUIRE_INDEX_COUNT_MATCH and not (ready_count <= entity_count <= recoverable_upper_bound):
            raise SystemExit(
                "Milvus/RDS vector count mismatch: entities={}, ready={}, pending={}. "
                "Rebuild or repair the collection before scheduled vectorization.".format(
                    entity_count,
                    ready_count,
                    pending_count,
                )
            )
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
        if failed == 0:
            collection.flush()
            final_ready_count = ready_embedding_count(conn)
            final_pending_count = pending_embedding_count(conn)
            final_entity_count = int(collection.num_entities)
            rds_ids: set[int] = set()
            milvus_ids: set[int] = set()
            if final_pending_count == 0 and final_entity_count == final_ready_count and final_ready_count > 0:
                rds_ids = ready_embedding_ids(conn)
                milvus_ids = collection_image_ids(collection)
            if (
                final_pending_count == 0
                and final_ready_count > 0
                and len(rds_ids) == final_ready_count
                and rds_ids == milvus_ids
            ):
                if READY_MARKER_PATH is not None:
                    write_ready_marker(rds_ids)
                    print("Full vector coverage marker written: {}.".format(READY_MARKER_PATH))
            else:
                remove_ready_marker()
                print(
                    "Vector coverage is incomplete: entities={}, ready={}, pending={}.".format(
                        final_entity_count,
                        final_ready_count,
                        final_pending_count,
                    )
                )
                if final_pending_count == 0:
                    raise SystemExit(
                        "Full vector coverage verification failed: RDS and Milvus image ID sets differ."
                    )
    print("Done. embedded={}, failed={}".format(ok, failed))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    start = time.time()
    run()
    print("Elapsed {:.0f}s".format(time.time() - start))
