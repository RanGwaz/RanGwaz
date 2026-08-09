from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", line):
            key, value = line.split("=", 1)
            values[key] = value
    return values


class VectorJobProductionSafetyTest(unittest.TestCase):
    def test_units_use_low_privilege_user_minimal_env_and_explicit_bash(self):
        vectorize = read("ops/jobs/systemd/vibelo-vectorize.service")
        recall = read("ops/jobs/systemd/vibelo-vector-recall.service")

        for unit in (vectorize, recall):
            self.assertIn("ProtectSystem=strict", unit)
            self.assertNotIn(".env.public", unit)
            self.assertRegex(unit, r"(?m)^ExecStart=.*?/usr/bin/bash(?:\s|$)")

        self.assertIn("User=vibelo-vectorize", vectorize)
        self.assertIn("Group=vibelo-vectorize", vectorize)
        self.assertIn("User=vibelo-vector-recall", recall)
        self.assertIn("Group=vibelo-vector-recall", recall)
        self.assertIn("SupplementaryGroups=vibelo-vector-runtime", vectorize)
        self.assertIn("SupplementaryGroups=vibelo-vector-runtime", recall)
        self.assertIn("EnvironmentFile=/etc/vibelo/vector-db.env", vectorize)
        self.assertNotIn("vector-db.env", recall)
        self.assertIn("RuntimeDirectory=vibelo-vector-jobs", vectorize)
        self.assertIn(
            "ReadWritePaths=/data/vibelo-vector/cache /data/vibelo-vector/state /run/vibelo-vector-jobs",
            vectorize,
        )

    def test_model_caches_are_under_data_and_huggingface_is_offline(self):
        example = env_values(read("ops/jobs/vector-job.env.example"))
        for key in (
            "MODEL_CACHE_ROOT",
            "VIBELO_HF_HOME",
            "TORCH_HOME",
            "XDG_CACHE",
            "XDG_CACHE_HOME",
            "VIBELO_VECTOR_READY_MARKER",
        ):
            self.assertIn(key, example)
            self.assertTrue(example[key].startswith("/data/"), (key, example[key]))
        for key in (
            "VIBELO_MODEL_OFFLINE",
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "HF_DATASETS_OFFLINE",
        ):
            self.assertEqual("1", example.get(key))

        worker = read("tools/vectorize_images.py")
        runner = read("ops/jobs/run-vectorize-job.sh")
        self.assertIn("local_files_only=OFFLINE_MODE", worker)
        self.assertIn("MODEL_CACHE_ROOT", worker)
        self.assertIn("write_ready_marker", worker)
        self.assertIn("final_pending_count == 0", worker)
        self.assertIn("require_data_path", runner)

    def test_installer_extracts_only_db_env_and_discovers_backend_bridge(self):
        installer = read("ops/jobs/install-vector-timer.sh")

        self.assertIn("vibelo-vector", installer)
        self.assertIn("vector-db.env", installer)
        self.assertIn("0640", installer)
        self.assertIn("VIBELO_DB_PASSWORD", installer)
        self.assertIn("SENSITIVE_SERVICE_GROUPS=(root docker sudo wheel adm lxd systemd-journal)", installer)
        self.assertIn('assert_safe_service_groups "$user"', installer)
        self.assertIn('id -nG "$user"', installer)
        self.assertNotRegex(installer, r"(?m)^\s*(?:source|\.)\s+.*\.env\.public")
        self.assertIn("com.docker.compose.project=vibelo-public", installer)
        self.assertIn("com.docker.compose.service=backend", installer)
        self.assertIn("docker network inspect", installer)
        self.assertIn("host.docker.internal", installer)
        self.assertIn("VECTOR_SERVICE_URL", installer)
        self.assertIn("verify_recall_listener", installer)
        self.assertIn("docker exec", installer)
        self.assertIn("--enable-recall", installer)
        self.assertIn("systemctl restart vibelo-vector-recall.service", installer)
        self.assertIn("systemctl disable vibelo-vector-recall.service", installer)
        self.assertIn("cannot disable unvalidated vector recall autostart", installer)
        self.assertIn("validate_ready_marker", installer)
        self.assertIn("full vector coverage marker is missing", installer)
        self.assertLess(
            installer.index("((enable_recall == 0)) || VALIDATING_RECALL=1"),
            installer.index('((enable_recall == 0)) || validate_ready_marker "$TEMP_JOB_ENV"'),
        )
        self.assertNotIn("systemctl enable --now vibelo-vector-recall.service", installer)
        self.assertIn('install -d -o root -g root -m 0755 "$CONFIG_DIR"', installer)
        self.assertIn('TEMP_DB_ENV=$(mktemp "$CONFIG_DIR/.vector-db.candidate.', installer)
        self.assertLess(
            installer.index('\n  pause_vector_timer\n'),
            installer.index('extract_minimal_db_env "$TEMP_DB_ENV"'),
        )
        self.assertIn("CONFIG_PUBLISH_STARTED=1", installer)
        self.assertIn('mv -f -- "$TEMP_DB_ENV" "$DB_ENV"', installer)
        self.assertIn('mv -f -- "$TEMP_JOB_ENV" "$JOB_ENV"', installer)
        self.assertIn('runuser -u "$RECALL_USER" -- test -r "$TEMP_DB_ENV"', installer)
        self.assertIn("VIBELO_EMBED_PROJECTION_VERSION", installer)

    def test_installer_proves_vector_timer_is_quiesced_before_publishing(self):
        installer = read("ops/jobs/install-vector-timer.sh")
        pause = installer.split("pause_vector_timer() {", 1)[1].split("\n}\n", 1)[0]

        self.assertIn("TIMER_ENABLE_STATE=$(systemctl is-enabled", pause)
        self.assertIn("TIMER_QUIESCED=1", pause)
        self.assertIn("systemctl disable --now vibelo-vectorize.timer", pause)
        self.assertNotIn("disable --now vibelo-vectorize.timer >/dev/null 2>&1 || true", pause)
        self.assertIn("vibelo-vectorize.timer is still active after disable --now", pause)
        self.assertIn("vibelo-vectorize.timer is still enabled after disable --now", pause)
        self.assertLess(
            installer.index("\n  pause_vector_timer\n"),
            installer.index('extract_minimal_db_env "$TEMP_DB_ENV"'),
        )
        self.assertIn("restore_vector_timer_before_publish", installer)

    def test_projection_version_is_bound_to_job_marker_and_recall(self):
        example = env_values(read("ops/jobs/vector-job.env.example"))
        expected = "siglip-image-feature-l2-rp512-seed20260606-v1"
        self.assertEqual(expected, example.get("VIBELO_EMBED_PROJECTION_VERSION"))
        self.assertIn('"projectionVersion": PROJECTION_VERSION', read("tools/vectorize_images.py"))
        self.assertIn('"projectionVersion": PROJECTION_VERSION', read("tools/vector_recall_service.py"))
        self.assertIn("SUPPORTED_PROJECTION_VERSION", read("ops/jobs/run-vectorize-job.sh"))

    def test_recall_bind_is_configurable_and_fail_closed(self):
        service = read("tools/vector_recall_service.py")
        example = env_values(read("ops/jobs/vector-job.env.example"))

        self.assertIn("VIBELO_VECTOR_RECALL_HOST", service)
        self.assertIn("VIBELO_VECTOR_RECALL_PORT", service)
        self.assertIn("validate_service_bind_host", service)
        self.assertIn("uvicorn.run(app, host=SERVICE_HOST, port=SERVICE_PORT)", service)
        self.assertIn('expected="${BACKEND_GATEWAY}:${RECALL_PORT}"', read("ops/jobs/install-vector-timer.sh"))
        self.assertIn('[[ ${listeners[0]} == "$expected" ]]', read("ops/jobs/install-vector-timer.sh"))
        self.assertIn('coll is not None and entities > 0', service)
        self.assertNotEqual("0.0.0.0", example.get("VIBELO_VECTOR_RECALL_HOST"))
        self.assertEqual("1", example.get("VIBELO_REQUIRE_PRIVATE_BRIDGE_BIND"))


if __name__ == "__main__":
    unittest.main()
