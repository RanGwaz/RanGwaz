from __future__ import annotations

import unittest
from unittest import mock

from tools import recommendation_model_service as service


class _EmptyRegistry:
    def __init__(self) -> None:
        self.base_dirs = []

    def get_entry(self, slot, base_dir=None):
        self.base_dirs.append(base_dir)
        return None


class TwoTowerServingTest(unittest.TestCase):
    def setUp(self) -> None:
        service._TWO_TOWER_MODEL = None
        service._TWO_TOWER_PAYLOAD = {}
        service._TWO_TOWER_ENTRY = {}
        service._TWO_TOWER_REGISTRY_MTIME = None
        service._TWO_TOWER_CHECKED = False
        service._TWO_TOWER_VERSION = None
        service._TWO_TOWER_INDEX_COLLECTION = None
        service._TWO_TOWER_LOAD_ERROR = None
        service._TWO_TOWER_LAST_CHECK_AT = 0.0

    def test_registry_root_is_not_double_nested_and_failures_retry(self) -> None:
        registry = _EmptyRegistry()
        retrieval = object()
        clock = [100.0]
        with mock.patch.object(service, "_registry_mtime", return_value=42), \
                mock.patch.object(
                    service,
                    "_two_tower_modules",
                    return_value=(registry, retrieval),
                ), \
                mock.patch.object(service.time, "monotonic", side_effect=lambda: clock[0]):
            self.assertEqual((None, {}, None), service.load_two_tower())
            self.assertEqual([service.MODEL_DIR], registry.base_dirs)

            clock[0] += service.TWO_TOWER_RETRY_SECONDS / 2
            self.assertEqual((None, {}, None), service.load_two_tower())
            self.assertEqual(1, len(registry.base_dirs))

            clock[0] += service.TWO_TOWER_RETRY_SECONDS
            self.assertEqual((None, {}, None), service.load_two_tower())
            self.assertEqual(
                [service.MODEL_DIR, service.MODEL_DIR],
                registry.base_dirs,
            )

    def test_recall_response_identifies_learned_and_fallback_modes(self) -> None:
        learned = service.RecallResponse(
            hits=[],
            mode="trained-two-tower",
            source="learned-two-tower",
            modelVersion="v1",
            indexCollection="learned_v1",
        )
        self.assertEqual("v1", learned.modelVersion)
        self.assertEqual("learned_v1", learned.indexCollection)

        fallback = service.RecallResponse(hits=[])
        self.assertEqual("heuristic", fallback.mode)
        self.assertEqual("siglip-multi-interest", fallback.source)
        self.assertIsNone(fallback.modelVersion)
