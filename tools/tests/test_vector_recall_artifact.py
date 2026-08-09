from __future__ import annotations

import json
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


# The production dependency is installed only in .venv-vector. Unit tests use a
# tiny protocol-compatible module so the artifact gates can run in the regular
# repository test environment without connecting to Milvus.
if "pymilvus" not in sys.modules and importlib.util.find_spec("pymilvus") is None:
    pymilvus = types.ModuleType("pymilvus")
    pymilvus.Collection = object
    pymilvus.connections = types.SimpleNamespace(connect=lambda **_: None)
    pymilvus.utility = types.SimpleNamespace(has_collection=lambda _: False)
    sys.modules["pymilvus"] = pymilvus

from tools import vector_recall_service as recall


class _Field:
    name = "embedding"
    params = {"dim": 512}


class _Index:
    field_name = "embedding"
    params = {"metric_type": "COSINE", "index_type": "HNSW"}


class _Iterator:
    def __init__(self, image_ids: set[int]):
        self._batches = [[{"image_id": item} for item in sorted(image_ids)], []]
        self.closed = False

    def next(self):
        return self._batches.pop(0)

    def close(self):
        self.closed = True


class _Collection:
    def __init__(self, image_ids: set[int]):
        self.image_ids = image_ids
        self.num_entities = len(image_ids)
        self.schema = types.SimpleNamespace(fields=[_Field()])
        self.indexes = [_Index()]
        self.loaded = False

    def query_iterator(self, **_):
        return _Iterator(self.image_ids)

    def load(self):
        self.loaded = True


class VectorRecallArtifactTest(unittest.TestCase):
    def setUp(self):
        self.old_collection = recall._COLLECTION
        self.old_signature = recall._MARKER_SIGNATURE
        recall._COLLECTION = None
        recall._MARKER_SIGNATURE = None

    def tearDown(self):
        recall._COLLECTION = self.old_collection
        recall._MARKER_SIGNATURE = self.old_signature

    @staticmethod
    def marker_payload(image_ids: set[int]) -> dict:
        return {
            "collection": recall.MILVUS_COLLECTION,
            "dimension": recall.VECTOR_DIMENSION,
            "entities": len(image_ids),
            "idSetSha256": recall.id_set_sha256(image_ids),
            "metric": "COSINE",
            "model": recall.MODEL_NAME,
            "projectionVersion": recall.PROJECTION_VERSION,
            "ready": len(image_ids),
            "vectorVersion": recall.VECTOR_VERSION,
        }

    @staticmethod
    def replace_json(path: Path, payload: dict) -> None:
        temporary = path.with_suffix(".next")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def test_ready_marker_rejects_bad_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready.json"
            payload = self.marker_payload({1, 2})
            payload["idSetSha256"] = "not-a-sha256"
            marker.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(recall, "REQUIRE_READY_MARKER", True), patch.object(
                recall, "READY_MARKER_PATH", marker
            ):
                self.assertEqual((None, None), recall.ready_marker())

    def test_ready_marker_rejects_other_projection_version(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready.json"
            payload = self.marker_payload({1, 2})
            payload["projectionVersion"] = "different-projection-v2"
            marker.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(recall, "REQUIRE_READY_MARKER", True), patch.object(
                recall, "READY_MARKER_PATH", marker
            ):
                self.assertEqual((None, None), recall.ready_marker())

    def test_marker_replacement_invalidates_cached_collection(self):
        image_ids = {11, 22}
        first = _Collection(image_ids)
        second = _Collection(image_ids)
        factory = Mock(side_effect=[first, second])
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready.json"
            payload = self.marker_payload(image_ids)
            self.replace_json(marker, payload)
            with patch.object(recall, "REQUIRE_READY_MARKER", True), patch.object(
                recall, "READY_MARKER_PATH", marker
            ), patch.object(recall, "Collection", factory), patch.object(
                recall.utility, "has_collection", return_value=True
            ), patch.object(recall.connections, "connect"):
                self.assertIs(first, recall.collection())
                payload["generatedAt"] = "replacement"
                self.replace_json(marker, payload)
                self.assertIs(second, recall.collection())

        self.assertEqual(2, factory.call_count)
        self.assertTrue(first.loaded)
        self.assertTrue(second.loaded)

    def test_missing_marker_invalidates_cached_collection(self):
        recall._COLLECTION = _Collection({1})
        recall._MARKER_SIGNATURE = (1, 2, 3)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            recall, "REQUIRE_READY_MARKER", True
        ), patch.object(recall, "READY_MARKER_PATH", Path(directory) / "missing.json"):
            self.assertIsNone(recall.collection())
        self.assertIsNone(recall._COLLECTION)
        self.assertIsNone(recall._MARKER_SIGNATURE)

    def test_collection_artifact_requires_one_hnsw_cosine_index(self):
        collection = _Collection({1})
        self.assertTrue(recall.validate_collection_artifact(collection))
        collection.indexes = []
        self.assertFalse(recall.validate_collection_artifact(collection))
        collection.indexes = [_Index(), _Index()]
        self.assertFalse(recall.validate_collection_artifact(collection))


if __name__ == "__main__":
    unittest.main()
