#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Publish a versioned two-tower item index from the canonical SigLIP vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:
    from .two_tower_registry import (
        RegistryError, get_entry, mark_indexed, model_root, promote,
    )
    from .two_tower_retrieval import load_two_tower_checkpoint
except ImportError:
    from two_tower_registry import (
        RegistryError, get_entry, mark_indexed, model_root, promote,
    )
    from two_tower_retrieval import load_two_tower_checkpoint

SOURCE_DIMENSION = 512
VECTOR_FIELD = "embedding"
DEFAULT_SOURCE_COLLECTION = os.environ.get(
    "VIBELO_MILVUS_COLLECTION",
    "vibelo_image_vectors_siglip2_base_p224_d512",
)


def chunks(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def safe_collection_name(version: str) -> str:
    safe_version = re.sub(r"[^A-Za-z0-9_]", "_", version).strip("_").lower()
    if not safe_version:
        raise ValueError("version cannot be converted to a safe Milvus name")
    version_hash = hashlib.sha1(version.encode("utf-8")).hexdigest()[:12]
    name = f"vibelo_two_tower_{safe_version}_{version_hash}"
    if len(name) > 255:
        prefix_length = 255 - len("vibelo_two_tower__") - len(version_hash)
        name = f"vibelo_two_tower_{safe_version[:prefix_length]}_{version_hash}"
    return name


def protected_collection_names(base_dir: Optional[str]) -> set[str]:
    result: set[str] = set()
    for slot in ("current", "previous"):
        entry = get_entry(slot, base_dir=base_dir)
        index = entry.get("index") if entry else None
        if isinstance(index, Mapping):
            collection = str(index.get("collection") or "").strip()
            if collection:
                result.add(collection)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        while True:
            block = input_file.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def read_manifest(entry: Mapping[str, Any], base_dir: Optional[str]) -> Dict[str, Any]:
    path = model_root(base_dir) / str(entry["manifestPath"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read candidate manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != entry.get("version"):
        raise RuntimeError("candidate manifest does not match its registry entry")
    return payload


def _mode(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    training_metadata = payload.get("training_metadata")
    values = [
        data.get("mode") if isinstance(data, Mapping) else None,
        payload.get("mode"),
        training_metadata.get("data_mode")
        if isinstance(training_metadata, Mapping)
        else None,
        training_metadata.get("mode")
        if isinstance(training_metadata, Mapping)
        else None,
    ]
    return str(next((value for value in values if value), "")).strip().lower()


def _gates_passed(payload: Mapping[str, Any]) -> Optional[bool]:
    training = payload.get("training")
    training_metadata = payload.get("training_metadata")
    values = [
        training.get("gatesPassed") if isinstance(training, Mapping) else None,
        training.get("gates_passed") if isinstance(training, Mapping) else None,
        payload.get("gatesPassed"),
        training_metadata.get("gates_passed")
        if isinstance(training_metadata, Mapping)
        else None,
        training_metadata.get("gatesPassed")
        if isinstance(training_metadata, Mapping)
        else None,
    ]
    return next((value for value in values if isinstance(value, bool)), None)


def enforce_release_gate(
    manifest: Mapping[str, Any],
    checkpoint: Optional[Mapping[str, Any]],
    allow_unsafe: bool,
    promoting: bool,
) -> None:
    modes = {_mode(manifest)}
    if checkpoint is not None:
        modes.add(_mode(checkpoint))
    modes.discard("")
    is_synthetic = any(mode.startswith("synthetic") for mode in modes)
    gate_values = [_gates_passed(manifest)]
    if checkpoint is not None:
        gate_values.append(_gates_passed(checkpoint))
    manifest_gates_passed = gate_values[0] is True
    checkpoint_gates_failed = (
        len(gate_values) > 1 and gate_values[1] is False
    )
    gates_passed = manifest_gates_passed and not checkpoint_gates_failed
    if is_synthetic and promoting:
        raise RuntimeError("synthetic smoke models can never be promoted")
    if (is_synthetic or not gates_passed) and not allow_unsafe:
        reason = "synthetic data" if is_synthetic else "training gates were not passed"
        raise RuntimeError(
            f"refusing to publish candidate built with {reason}; "
            "use --allow-unsafe only for isolated smoke validation"
        )


def resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError as exc:
        raise SystemExit(
            "Missing torch. Install tools/requirements_recommendation.txt first."
        ) from exc
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_candidate(args: argparse.Namespace):
    entry = get_entry("candidate", base_dir=args.model_dir)
    if not entry:
        raise RegistryError("no two-tower candidate is registered")
    if args.version and entry["version"] != args.version:
        raise RegistryError(
            f"registered candidate is {entry['version']!r}, not {args.version!r}"
        )
    version = str(entry["version"])
    manifest = read_manifest(entry, args.model_dir)
    enforce_release_gate(manifest, None, args.allow_unsafe, args.promote)
    checkpoint_path = model_root(args.model_dir) / entry["modelPath"]
    expected_sha = str(manifest.get("sha256") or "").strip().lower()
    if expected_sha:
        actual_sha = sha256_file(checkpoint_path)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"checkpoint checksum mismatch: expected {expected_sha}, got {actual_sha}"
            )
    device = resolve_device(args.device)
    model, checkpoint = load_two_tower_checkpoint(checkpoint_path, device=device)
    if str(checkpoint.get("version") or version) != version:
        raise RuntimeError("checkpoint version does not match registry version")
    enforce_release_gate(manifest, checkpoint, args.allow_unsafe, args.promote)
    if int(model.config.input_dim) != SOURCE_DIMENSION:
        raise RuntimeError(
            f"item tower requires {model.config.input_dim} source dimensions, "
            f"expected {SOURCE_DIMENSION}"
        )
    return entry, manifest, model, checkpoint, device


def require_pymysql():
    try:
        import pymysql
    except ImportError as exc:
        raise SystemExit(
            "Missing pymysql. Install tools/requirements_recommendation.txt first."
        ) from exc
    return pymysql


def load_published_ids(args: argparse.Namespace) -> Tuple[int, List[int]]:
    pymysql = require_pymysql()
    connection = pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=args.mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM images WHERE status='PUBLISHED'")
            total = int(cursor.fetchone()["count"])
            sql = "SELECT id FROM images WHERE status='PUBLISHED' ORDER BY id"
            if args.limit > 0:
                sql += f" LIMIT {int(args.limit)}"
            cursor.execute(sql)
            image_ids = [int(row["id"]) for row in cursor.fetchall()]
    finally:
        connection.close()
    if not image_ids:
        raise RuntimeError("MySQL contains no PUBLISHED images to index")
    return total, image_ids


def require_milvus():
    try:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            connections,
            utility,
        )
    except ImportError as exc:
        raise SystemExit(
            "Missing pymilvus. Install tools/requirements_recommendation.txt first."
        ) from exc
    return Collection, CollectionSchema, DataType, FieldSchema, connections, utility


def field_dimension(collection, field_name: str) -> int:
    for field in collection.schema.fields:
        if field.name == field_name:
            return int(field.params.get("dim") or 0)
    raise RuntimeError(f"collection {collection.name!r} has no field {field_name!r}")


def connect_source(args: argparse.Namespace):
    Collection, _, _, _, connections, utility = require_milvus()
    connections.connect(alias="default", host=args.milvus_host, port=args.milvus_port)
    if not utility.has_collection(args.source_collection):
        raise RuntimeError(f"source collection not found: {args.source_collection}")
    source = Collection(args.source_collection)
    if field_dimension(source, args.source_vector_field) != SOURCE_DIMENSION:
        raise RuntimeError(
            f"source field {args.source_vector_field!r} must be {SOURCE_DIMENSION}D"
        )
    source.load()
    return source


def create_target(name: str, dimension: int):
    Collection, CollectionSchema, DataType, FieldSchema, _, _ = require_milvus()
    fields = [
        FieldSchema(
            name="image_id", dtype=DataType.INT64, is_primary=True, auto_id=False
        ),
        FieldSchema(name="source_image_id", dtype=DataType.INT64),
        FieldSchema(name=VECTOR_FIELD, dtype=DataType.FLOAT_VECTOR, dim=dimension),
    ]
    return Collection(
        name=name,
        schema=CollectionSchema(
            fields=fields,
            description="Versioned Vibelo learned two-tower item vectors",
        ),
    )


def source_vectors(
    source, image_ids: Sequence[int], vector_field: str
) -> Tuple[List[int], np.ndarray]:
    expression = "image_id in [{}]".format(",".join(str(value) for value in image_ids))
    rows = source.query(
        expr=expression,
        output_fields=["image_id", vector_field],
    )
    by_id = {int(row["image_id"]): row.get(vector_field) for row in rows}
    missing = [value for value in image_ids if by_id.get(value) is None]
    if missing:
        preview = ", ".join(str(value) for value in missing[:10])
        raise RuntimeError(
            f"source vectors missing for {len(missing)} PUBLISHED images: {preview}"
        )
    matrix = np.asarray([by_id[value] for value in image_ids], dtype=np.float32)
    if matrix.shape != (len(image_ids), SOURCE_DIMENSION) or not np.isfinite(matrix).all():
        raise RuntimeError(f"invalid source vector matrix shape {matrix.shape}")
    return list(image_ids), matrix


def encode_batch(model, device: str, vectors: np.ndarray) -> np.ndarray:
    import torch

    with torch.inference_mode():
        tensor = torch.from_numpy(vectors).to(device)
        encoded = model.encode_item(tensor).detach().float().cpu().numpy()
    if encoded.ndim != 2 or not np.isfinite(encoded).all():
        raise RuntimeError(f"item tower produced invalid shape {encoded.shape}")
    norms = np.linalg.norm(encoded, axis=1)
    if not np.all((norms >= 0.99) & (norms <= 1.01)):
        raise RuntimeError(
            f"item tower output is not normalized; norm range "
            f"{float(norms.min()):.6f}..{float(norms.max()):.6f}"
        )
    return encoded.astype(np.float32, copy=False)


def sample_ids(image_ids: Sequence[int], size: int) -> List[int]:
    if len(image_ids) <= size:
        return list(image_ids)
    if size <= 1:
        return [image_ids[0]]
    indexes = {
        int(round(index * (len(image_ids) - 1) / (size - 1)))
        for index in range(size)
    }
    return [image_ids[index] for index in sorted(indexes)]


def validate_target(
    collection,
    expected_count: int,
    expected_dimension: int,
    image_ids: Sequence[int],
    sample_size: int,
) -> Dict[str, float]:
    collection.flush()
    collection.load()
    entity_count = int(collection.num_entities)
    if entity_count != expected_count:
        raise RuntimeError(
            f"target entity count is {entity_count}, expected {expected_count}"
        )
    if field_dimension(collection, VECTOR_FIELD) != expected_dimension:
        raise RuntimeError("target vector dimension does not match checkpoint")
    selected = sample_ids(image_ids, sample_size)
    expression = "image_id in [{}]".format(",".join(str(value) for value in selected))
    rows = collection.query(
        expr=expression,
        output_fields=["image_id", "source_image_id", VECTOR_FIELD],
    )
    if len(rows) != len(selected):
        raise RuntimeError("target validation sample is incomplete")
    norms: List[float] = []
    for row in rows:
        if int(row["source_image_id"]) != int(row["image_id"]):
            raise RuntimeError("source_image_id does not match image_id")
        vector = np.asarray(row[VECTOR_FIELD], dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or not 0.98 <= norm <= 1.02:
            raise RuntimeError(f"target contains an invalid vector norm {norm}")
        norms.append(norm)
    return {
        "entityCount": entity_count,
        "sampleCount": len(norms),
        "minNorm": min(norms),
        "maxNorm": max(norms),
    }


def publish(args: argparse.Namespace) -> Dict[str, Any]:
    entry, manifest, model, _, device = load_candidate(args)
    version = entry["version"]
    target_name = safe_collection_name(version)
    dimension = int(model.config.embedding_dim)
    total_published, image_ids = load_published_ids(args)
    partial = len(image_ids) < total_published
    if partial and args.promote:
        raise RuntimeError("--limit creates a partial index and can never be promoted")
    source = connect_source(args)
    _, _, _, _, _, utility = require_milvus()

    if args.dry_run:
        encoded_count = 0
        for batch in chunks(image_ids, args.batch_size):
            _, vectors = source_vectors(source, batch, args.source_vector_field)
            encoded_count += len(encode_batch(model, device, vectors))
        return {
            "dryRun": True,
            "version": version,
            "targetCollection": target_name,
            "publishedCount": total_published,
            "validatedCount": encoded_count,
            "partial": partial,
        }

    if utility.has_collection(target_name):
        if args.rebuild:
            if target_name in protected_collection_names(args.model_dir):
                raise RuntimeError(
                    f"refusing to rebuild active or rollback collection {target_name!r}"
                )
            utility.drop_collection(target_name)
        else:
            Collection, _, _, _, _, _ = require_milvus()
            target = Collection(target_name)
            validation = validate_target(
                target, len(image_ids), dimension, image_ids, args.sample_size
            )
            if partial:
                return {
                    "reused": True,
                    "partial": True,
                    "version": version,
                    "targetCollection": target_name,
                    **validation,
                }
            marked = mark_indexed(
                version, target_name, validation["entityCount"], base_dir=args.model_dir
            )
            if args.promote:
                promote(version, base_dir=args.model_dir)
            return {
                "reused": True,
                "promoted": bool(args.promote),
                "version": version,
                "targetCollection": target_name,
                "registryEntry": marked,
                **validation,
            }

    target = create_target(target_name, dimension)
    inserted = 0
    for batch_index, batch in enumerate(chunks(image_ids, args.batch_size), start=1):
        ids, raw_vectors = source_vectors(source, batch, args.source_vector_field)
        learned_vectors = encode_batch(model, device, raw_vectors)
        target.insert([ids, ids, learned_vectors.tolist()])
        inserted += len(ids)
        print(
            f"[batch {batch_index}] indexed {inserted}/{len(image_ids)}",
            flush=True,
        )
    target.flush()
    target.create_index(
        field_name=VECTOR_FIELD,
        index_params={
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 32, "efConstruction": 200},
        },
    )
    validation = validate_target(
        target, len(image_ids), dimension, image_ids, args.sample_size
    )
    if partial:
        return {
            "created": True,
            "partial": True,
            "version": version,
            "targetCollection": target_name,
            **validation,
        }
    marked = mark_indexed(
        version, target_name, validation["entityCount"], base_dir=args.model_dir
    )
    if args.promote:
        promote(version, base_dir=args.model_dir)
    return {
        "created": True,
        "promoted": bool(args.promote),
        "version": version,
        "targetCollection": target_name,
        "registryEntry": marked,
        **validation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish a versioned two-tower item collection to Milvus."
    )
    parser.add_argument("--version")
    parser.add_argument("--model-dir")
    parser.add_argument("--source-collection", default=DEFAULT_SOURCE_COLLECTION)
    parser.add_argument("--source-vector-field", default=VECTOR_FIELD)
    parser.add_argument(
        "--milvus-host",
        default=os.environ.get("VIBELO_MILVUS_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--milvus-port",
        default=os.environ.get("VIBELO_MILVUS_PORT", "19530"),
    )
    parser.add_argument(
        "--mysql-host",
        default=os.environ.get(
            "VIBELO_MYSQL_HOST", os.environ.get("VIBELO_DB_HOST", "127.0.0.1")
        ),
    )
    parser.add_argument(
        "--mysql-port",
        type=int,
        default=int(
            os.environ.get(
                "VIBELO_MYSQL_PORT", os.environ.get("VIBELO_DB_PORT", "3306")
            )
        ),
    )
    parser.add_argument(
        "--mysql-database",
        default=os.environ.get(
            "VIBELO_MYSQL_DATABASE",
            os.environ.get("VIBELO_DB_NAME", "rangwaz_image_dev"),
        ),
    )
    parser.add_argument(
        "--mysql-user",
        default=os.environ.get(
            "VIBELO_MYSQL_USER", os.environ.get("VIBELO_DB_USER", "rangwaz")
        ),
    )
    parser.add_argument(
        "--mysql-password",
        default=os.environ.get(
            "VIBELO_MYSQL_PASSWORD",
            os.environ.get("VIBELO_DB_PASSWORD", "rangwaz123"),
        ),
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--sample-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--allow-unsafe", action="store_true")
    args = parser.parse_args()
    if args.batch_size <= 0 or args.sample_size <= 0 or args.limit < 0:
        parser.error(
            "--batch-size/--sample-size must be positive and --limit non-negative"
        )
    return args


def main() -> None:
    result = publish(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
