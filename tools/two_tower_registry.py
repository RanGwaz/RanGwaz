#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Atomic registry for versioned Vibelo two-tower model artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

PathLike = Union[str, os.PathLike[str]]
SCHEMA_VERSION = 1
SLOTS = ("candidate", "current", "previous")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get(
    "VIBELO_RECOMMENDATION_MODEL_DIR",
    BASE_DIR / "models" / "recommendation",
))


class RegistryError(RuntimeError):
    """The registry or one of its artifacts violates the storage contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_root(base_dir: Optional[PathLike] = None) -> Path:
    """Return MODEL_DIR/two_tower or base_dir/two_tower."""

    base = MODEL_DIR if base_dir is None else Path(base_dir)
    return base.expanduser().resolve() / "two_tower"


def _empty() -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": None,
        "entries": {slot: None for slot in SLOTS},
    }


def _version(value: object) -> str:
    result = str(value or "").strip()
    if not _VERSION_RE.fullmatch(result) or result in {".", ".."}:
        raise RegistryError(
            "version must start with a letter or digit and contain only "
            "letters, digits, '.', '_' or '-'"
        )
    return result


def _relative(value: object, name: str) -> str:
    text = str(value or "").strip()
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise RegistryError(f"{name} must be a path relative to the model root")
    return path.as_posix()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _registry_path(base_dir: Optional[PathLike]) -> Path:
    return model_root(base_dir) / "registry.json"


def _validated_entry(value: object, slot: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RegistryError(f"registry entry {slot!r} must be an object or null")
    entry = copy.deepcopy(value)
    entry["version"] = _version(entry.get("version"))
    for field in ("artifactDir", "manifestPath", "modelPath"):
        entry[field] = _relative(entry.get(field), field)
    index = entry.get("index")
    if not isinstance(index, dict):
        raise RegistryError(f"registry entry {slot!r} has no index metadata")
    status = str(index.get("status") or "").upper()
    if status not in {"PENDING", "READY"}:
        raise RegistryError(f"registry entry {slot!r} has invalid index status")
    index["status"] = status
    try:
        index["entityCount"] = int(index.get("entityCount") or 0)
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"registry entry {slot!r} has invalid entityCount") from exc
    return entry


def load_registry(base_dir: Optional[PathLike] = None) -> Dict[str, Any]:
    """Load a validated registry, or return a new in-memory registry."""

    path = _registry_path(base_dir)
    if not path.exists():
        return _empty()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != SCHEMA_VERSION:
        raise RegistryError(f"registry schemaVersion must be {SCHEMA_VERSION}")
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise RegistryError("registry entries must be an object")
    result = copy.deepcopy(payload)
    result["entries"] = {
        slot: _validated_entry(entries.get(slot), slot) for slot in SLOTS
    }
    return result


def _read_manifest(
    entry: Mapping[str, Any], base_dir: Optional[PathLike]
) -> Dict[str, Any]:
    path = model_root(base_dir) / _relative(entry.get("manifestPath"), "manifestPath")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read model manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RegistryError(f"model manifest {path} must be an object")
    if _version(manifest.get("version")) != entry.get("version"):
        raise RegistryError(f"manifest {path} does not match registry version")
    return manifest


def register_candidate(
    manifest: Mapping[str, Any], base_dir: Optional[PathLike] = None
) -> Dict[str, Any]:
    """Register an already-written model.pt as the next candidate."""

    if not isinstance(manifest, Mapping):
        raise RegistryError("manifest must be a mapping")
    version = _version(manifest.get("version"))
    root = model_root(base_dir)
    artifact_dir = Path("versions") / version
    model_path = artifact_dir / "model.pt"
    manifest_path = artifact_dir / "manifest.json"
    if not (root / model_path).is_file():
        raise RegistryError(f"write checkpoint before registering: {root / model_path}")

    normalized = copy.deepcopy(dict(manifest))
    supplied = normalized.get("artifact_path")
    if supplied:
        supplied_path = Path(str(supplied))
        if supplied_path.is_absolute():
            try:
                supplied_path = supplied_path.resolve().relative_to(root)
            except ValueError as exc:
                raise RegistryError("artifact_path must be inside the model root") from exc
        if supplied_path.as_posix() != model_path.as_posix():
            raise RegistryError(f"artifact_path must be {model_path.as_posix()!r}")
    normalized["artifact_path"] = model_path.as_posix()
    normalized["version"] = version
    normalized.setdefault("schema_version", SCHEMA_VERSION)
    source_index = {
        "status": "PENDING", "collection": None,
        "entityCount": 0, "indexedAt": None,
    }
    normalized["index"] = copy.deepcopy(source_index)

    registered_at = _now()
    entry = {
        "version": version,
        "artifactDir": artifact_dir.as_posix(),
        "manifestPath": manifest_path.as_posix(),
        "modelPath": model_path.as_posix(),
        "registeredAt": registered_at,
        "index": copy.deepcopy(source_index),
    }
    _atomic_json(root / manifest_path, normalized)
    registry = load_registry(base_dir)
    registry["entries"]["candidate"] = entry
    registry["updatedAt"] = registered_at
    _atomic_json(_registry_path(base_dir), registry)
    return copy.deepcopy(entry)


def get_entry(
    slot: str, base_dir: Optional[PathLike] = None
) -> Optional[Dict[str, Any]]:
    if slot not in SLOTS:
        raise RegistryError(f"unknown slot {slot!r}; expected one of {SLOTS}")
    return copy.deepcopy(load_registry(base_dir)["entries"][slot])


def mark_indexed(
    version: str,
    collection: str,
    entity_count: int,
    base_dir: Optional[PathLike] = None,
) -> Dict[str, Any]:
    """Mark every registered slot for a version as indexed and ready."""

    version = _version(version)
    collection = str(collection or "").strip()
    try:
        entity_count = int(entity_count)
    except (TypeError, ValueError) as exc:
        raise RegistryError("entity_count must be an integer") from exc
    if not collection or entity_count <= 0:
        raise RegistryError("collection is required and entity_count must be positive")
    registry = load_registry(base_dir)
    slots = [
        slot for slot in SLOTS
        if registry["entries"].get(slot)
        and registry["entries"][slot]["version"] == version
    ]
    if not slots:
        raise RegistryError(f"model version {version!r} is not registered")
    entry = registry["entries"][slots[0]]
    manifest = _read_manifest(entry, base_dir)
    index = {
        "status": "READY",
        "collection": collection,
        "entityCount": entity_count,
        "indexedAt": _now(),
    }
    manifest["index"] = copy.deepcopy(index)
    _atomic_json(model_root(base_dir) / entry["manifestPath"], manifest)
    for slot in slots:
        registry["entries"][slot]["index"] = copy.deepcopy(index)
    registry["updatedAt"] = index["indexedAt"]
    _atomic_json(_registry_path(base_dir), registry)
    return copy.deepcopy(registry["entries"][slots[0]])


def _require_ready(
    entry: Mapping[str, Any], base_dir: Optional[PathLike]
) -> None:
    manifest = _read_manifest(entry, base_dir)
    index = manifest.get("index")
    if not isinstance(index, dict):
        raise RegistryError("manifest has no index metadata")
    try:
        count = int(index.get("entityCount") or 0)
    except (TypeError, ValueError) as exc:
        raise RegistryError("manifest index entityCount is invalid") from exc
    if (
        str(index.get("status") or "").upper() != "READY"
        or count <= 0
        or not str(index.get("collection") or "").strip()
    ):
        raise RegistryError(
            f"model {entry.get('version')!r} requires a READY index with entityCount > 0"
        )

    data = manifest.get("data")
    mode = str(data.get("mode") if isinstance(data, dict) else "").strip().lower()
    if mode.startswith("synthetic"):
        raise RegistryError("synthetic smoke models can never be promoted")
    training = manifest.get("training")
    if not isinstance(training, dict) or training.get("gatesPassed") is not True:
        raise RegistryError("model training gates must pass before promotion")

    checkpoint_path = model_root(base_dir) / _relative(
        entry.get("modelPath"), "modelPath"
    )
    if not checkpoint_path.is_file():
        raise RegistryError(f"model checkpoint does not exist: {checkpoint_path}")
    expected_sha = str(manifest.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise RegistryError("manifest sha256 is missing or invalid")
    digest = hashlib.sha256()
    with checkpoint_path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected_sha:
        raise RegistryError("model checkpoint sha256 does not match manifest")


def promote(version: str, base_dir: Optional[PathLike] = None) -> Dict[str, Any]:
    """Promote candidate to current and move current to previous."""

    version = _version(version)
    registry = load_registry(base_dir)
    candidate = registry["entries"].get("candidate")
    if not candidate or candidate["version"] != version:
        raise RegistryError(f"candidate version {version!r} is not registered")
    _require_ready(candidate, base_dir)
    now = _now()
    promoted = copy.deepcopy(candidate)
    promoted["promotedAt"] = now
    registry["entries"]["previous"] = copy.deepcopy(registry["entries"].get("current"))
    registry["entries"]["current"] = promoted
    registry["entries"]["candidate"] = None
    registry["updatedAt"] = now
    _atomic_json(_registry_path(base_dir), registry)
    return copy.deepcopy(promoted)


def rollback(base_dir: Optional[PathLike] = None) -> Dict[str, Any]:
    """Swap current and previous, allowing an immediate roll-forward."""

    registry = load_registry(base_dir)
    previous = registry["entries"].get("previous")
    if not previous:
        raise RegistryError("no previous model is available for rollback")
    _require_ready(previous, base_dir)
    now = _now()
    current = copy.deepcopy(registry["entries"].get("current"))
    restored = copy.deepcopy(previous)
    restored["rolledBackAt"] = now
    registry["entries"]["current"] = restored
    registry["entries"]["previous"] = current
    registry["updatedAt"] = now
    _atomic_json(_registry_path(base_dir), registry)
    return copy.deepcopy(restored)
