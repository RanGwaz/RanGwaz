from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.two_tower_registry import (
    RegistryError,
    get_entry,
    load_registry,
    mark_indexed,
    model_root,
    promote,
    register_candidate,
    rollback,
)


class TwoTowerRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temporary.name) / "models" / "recommendation"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_checkpoint(self, version: str) -> Path:
        path = model_root(self.base_dir) / "versions" / version / "model.pt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"checkpoint")
        return path

    def manifest(self, version: str) -> dict:
        checkpoint = model_root(self.base_dir) / "versions" / version / "model.pt"
        return {
            "schema_version": 1,
            "model_name": "vibelo-two-tower",
            "version": version,
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "data": {"mode": "behavior", "sample_count": 100},
            "training": {"gatesPassed": True},
            "config": {"input_dim": 512, "embedding_dim": 256},
        }

    def register_ready(self, version: str, count: int = 10) -> None:
        self.write_checkpoint(version)
        register_candidate(self.manifest(version), base_dir=self.base_dir)
        mark_indexed(
            version,
            f"vibelo_two_tower_{version}",
            count,
            base_dir=self.base_dir,
        )

    def test_register_candidate_writes_relative_atomic_layout(self) -> None:
        self.write_checkpoint("v1")
        entry = register_candidate(self.manifest("v1"), base_dir=self.base_dir)

        root = model_root(self.base_dir)
        registry_path = root / "registry.json"
        manifest_path = root / "versions" / "v1" / "manifest.json"
        self.assertTrue(registry_path.is_file())
        self.assertTrue(manifest_path.is_file())
        self.assertEqual("versions/v1", entry["artifactDir"])
        self.assertEqual("versions/v1/model.pt", entry["modelPath"])
        self.assertFalse(Path(entry["modelPath"]).is_absolute())
        self.assertEqual("PENDING", entry["index"]["status"])

        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(1, raw["schemaVersion"])
        self.assertEqual(
            {"candidate", "current", "previous"},
            set(raw["entries"]),
        )
        self.assertEqual("v1", raw["entries"]["candidate"]["version"])
        self.assertEqual([], list(root.rglob("*.tmp")))

    def test_promote_requires_ready_index_and_moves_current_to_previous(self) -> None:
        self.write_checkpoint("v1")
        register_candidate(self.manifest("v1"), base_dir=self.base_dir)
        with self.assertRaises(RegistryError):
            promote("v1", base_dir=self.base_dir)

        marked = mark_indexed(
            "v1", "vibelo_two_tower_v1", 23, base_dir=self.base_dir
        )
        self.assertEqual("READY", marked["index"]["status"])
        self.assertEqual(23, marked["index"]["entityCount"])
        manifest = json.loads(
            (
                model_root(self.base_dir)
                / "versions"
                / "v1"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("READY", manifest["index"]["status"])
        self.assertEqual(23, manifest["index"]["entityCount"])

        promoted = promote("v1", base_dir=self.base_dir)
        self.assertEqual("v1", promoted["version"])
        self.assertIsNone(get_entry("candidate", base_dir=self.base_dir))
        self.assertEqual("v1", get_entry("current", base_dir=self.base_dir)["version"])
        self.assertIsNone(get_entry("previous", base_dir=self.base_dir))

        self.register_ready("v2", count=24)
        promote("v2", base_dir=self.base_dir)
        self.assertEqual("v2", get_entry("current", base_dir=self.base_dir)["version"])
        self.assertEqual("v1", get_entry("previous", base_dir=self.base_dir)["version"])

    def test_rollback_swaps_current_and_previous(self) -> None:
        self.register_ready("v1")
        promote("v1", base_dir=self.base_dir)
        self.register_ready("v2")
        promote("v2", base_dir=self.base_dir)

        restored = rollback(base_dir=self.base_dir)

        self.assertEqual("v1", restored["version"])
        self.assertEqual("v1", get_entry("current", base_dir=self.base_dir)["version"])
        self.assertEqual("v2", get_entry("previous", base_dir=self.base_dir)["version"])

    def test_promote_rejects_synthetic_model(self) -> None:
        self.write_checkpoint("synthetic-v1")
        manifest = self.manifest("synthetic-v1")
        manifest["data"]["mode"] = "synthetic_smoke"
        register_candidate(manifest, base_dir=self.base_dir)
        mark_indexed(
            "synthetic-v1", "vibelo_two_tower_synthetic", 10,
            base_dir=self.base_dir,
        )
        with self.assertRaisesRegex(RegistryError, "synthetic"):
            promote("synthetic-v1", base_dir=self.base_dir)

    def test_promote_rejects_failed_training_gate(self) -> None:
        self.write_checkpoint("failed-gate-v1")
        manifest = self.manifest("failed-gate-v1")
        manifest["training"]["gatesPassed"] = False
        register_candidate(manifest, base_dir=self.base_dir)
        mark_indexed(
            "failed-gate-v1", "vibelo_two_tower_failed_gate", 10,
            base_dir=self.base_dir,
        )
        with self.assertRaisesRegex(RegistryError, "gates"):
            promote("failed-gate-v1", base_dir=self.base_dir)

    def test_promote_rejects_tampered_checkpoint(self) -> None:
        checkpoint = self.write_checkpoint("tampered-v1")
        register_candidate(self.manifest("tampered-v1"), base_dir=self.base_dir)
        mark_indexed(
            "tampered-v1", "vibelo_two_tower_tampered", 10,
            base_dir=self.base_dir,
        )
        checkpoint.write_bytes(b"tampered")
        with self.assertRaisesRegex(RegistryError, "sha256"):
            promote("tampered-v1", base_dir=self.base_dir)

    def test_failed_atomic_replace_preserves_registry_and_cleans_temp_file(self) -> None:
        self.register_ready("v1")
        promote("v1", base_dir=self.base_dir)
        before = load_registry(self.base_dir)
        self.write_checkpoint("v2")

        with mock.patch(
            "tools.two_tower_registry.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaises(OSError):
                register_candidate(self.manifest("v2"), base_dir=self.base_dir)

        self.assertEqual(before, load_registry(self.base_dir))
