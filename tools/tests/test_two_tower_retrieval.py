from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import torch
from torch.nn import functional as F

from tools.train_two_tower_recall import (
    BehaviorEvent,
    MatureExposure,
    TrainingExample,
    build_next_positive_examples,
    temporal_split,
)
from tools.two_tower_retrieval import (
    TwoTowerConfig,
    TwoTowerModel,
    duplicate_safe_info_nce,
    load_two_tower_checkpoint,
)


class TwoTowerModelTest(unittest.TestCase):
    def setUp(self) -> None:
        torch.manual_seed(17)
        self.config = TwoTowerConfig.from_dict({
            "max_sequence_length": 4,
            "transformer_layers": 1,
            "transformer_heads": 8,
            "transformer_feedforward_dim": 256,
            "dropout": 0.0,
            "future_manifest_field": "ignored",
        })
        self.model = TwoTowerModel(self.config).eval()

    def test_item_and_user_shapes_are_normalized(self) -> None:
        items = torch.randn(3, 512)
        item_embeddings = self.model.encode_item(items)
        self.assertEqual((3, 256), tuple(item_embeddings.shape))
        torch.testing.assert_close(
            item_embeddings.norm(dim=1), torch.ones(3), atol=1e-5, rtol=1e-5
        )

        histories = torch.randn(3, 4, 512)
        behavior_ids = torch.tensor([
            [5, 4, 3, 0],
            [6, 3, 0, 0],
            [4, 3, 2, 5],
        ])
        attention_mask = behavior_ids.ne(0)
        users = self.model.encode_user(
            histories,
            behavior_ids,
            torch.tensor([
                [1.0, 8.0, 24.0, 0.0],
                [2.0, 12.0, 0.0, 0.0],
                [1.0, 2.0, 3.0, 4.0],
            ]),
            torch.tensor([
                [12_000.0, 4_000.0, 3_500.0, 0.0],
                [8_000.0, 3_100.0, 0.0, 0.0],
                [7_000.0, 6_000.0, 5_000.0, 4_000.0],
            ]),
            attention_mask,
        )
        self.assertEqual((3, 256), tuple(users.shape))
        torch.testing.assert_close(
            users.norm(dim=1), torch.ones(3), atol=1e-5, rtol=1e-5
        )

    def test_checkpoint_round_trip_uses_public_loader(self) -> None:
        payload = {
            "format_version": "1",
            "model_name": "vibelo-two-tower-recall",
            "version": "test",
            "config": self.config.to_dict(),
            "behavior_to_id": {"padding": 0, "unknown": 1},
            "model_state_dict": self.model.state_dict(),
            "training_metadata": {"mode": "test"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            torch.save(payload, path)
            loaded, loaded_payload = load_two_tower_checkpoint(path, "cpu")
        self.assertFalse(loaded.training)
        self.assertEqual("test", loaded_payload["version"])
        source = torch.randn(2, 512)
        torch.testing.assert_close(
            self.model.encode_item(source),
            loaded.encode_item(source),
            atol=1e-6,
            rtol=1e-6,
        )

    def test_duplicate_safe_info_nce_decreases(self) -> None:
        target_embeddings = F.normalize(torch.randn(6, 256), dim=1)
        target_embeddings[2] = target_embeddings[1]
        target_ids = torch.tensor([10, 20, 20, 30, 40, 50])
        user_parameters = torch.nn.Parameter(torch.randn(6, 256))
        optimizer = torch.optim.Adam([user_parameters], lr=0.08)

        initial = float(duplicate_safe_info_nce(
            user_parameters, target_embeddings, target_ids, 0.10
        ).item())
        for _ in range(30):
            optimizer.zero_grad()
            loss = duplicate_safe_info_nce(
                user_parameters, target_embeddings, target_ids, 0.10
            )
            loss.backward()
            optimizer.step()
        final = float(duplicate_safe_info_nce(
            user_parameters, target_embeddings, target_ids, 0.10
        ).item())
        self.assertTrue(torch.isfinite(torch.tensor(final)))
        self.assertLess(final, initial * 0.35)


class TemporalSplitTest(unittest.TestCase):
    def test_examples_remove_same_image_leakage_and_require_mature_negative(self) -> None:
        base = datetime(2026, 1, 2, tzinfo=timezone.utc)
        events = [
            BehaviorEvent("u:1", 10, "impression", 0, base),
            BehaviorEvent("u:1", 10, "click", 0, base + timedelta(hours=1)),
            BehaviorEvent("u:1", 20, "view", 4_000, base + timedelta(hours=2)),
            BehaviorEvent("u:1", 30, "impression", 0, base + timedelta(hours=3)),
            BehaviorEvent("u:1", 30, "click", 0, base + timedelta(hours=4)),
            BehaviorEvent("u:1", 30, "like", 0, base + timedelta(hours=5)),
        ]
        exposures = [
            MatureExposure("u:1", 90, base - timedelta(hours=21)),
            MatureExposure("u:1", 91, base - timedelta(hours=19)),
        ]

        examples = build_next_positive_examples(events, exposures, 1, 8)

        self.assertEqual([20, 30], [item.target_image_id for item in examples])
        target = examples[-1]
        self.assertNotIn(30, {item.image_id for item in target.history})
        self.assertEqual(90, target.hard_negative_image_id)

    def test_global_temporal_split_is_80_10_10_without_shuffle(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        examples = []
        for index in range(10):
            history_event = BehaviorEvent(
                actor_key=f"u:{index % 3}",
                image_id=100 + index,
                behavior_type="view",
                duration_ms=4_000,
                occurred_at=base + timedelta(hours=index),
            )
            examples.append(TrainingExample(
                actor_key=history_event.actor_key,
                history=(history_event,),
                target_image_id=200 + index,
                target_behavior="click",
                target_at=base + timedelta(hours=index + 1),
            ))
        random.Random(3).shuffle(examples)
        train, validation, test = temporal_split(examples)

        self.assertEqual((8, 1, 1), (len(train), len(validation), len(test)))
        self.assertLessEqual(train[-1].target_at, validation[0].target_at)
        self.assertLessEqual(validation[-1].target_at, test[0].target_at)
        combined = train + validation + test
        self.assertEqual(
            sorted(item.target_at for item in examples),
            [item.target_at for item in combined],
        )


if __name__ == "__main__":
    unittest.main()
