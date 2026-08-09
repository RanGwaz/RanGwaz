from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from tools import dataset_collector, import_images, vectorize_images


class _Cursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []
        self.lastrowid = 99

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None

    def rollback(self):
        return None


class _CommitUncertainConnection(_Connection):
    def __init__(self, cursor):
        super().__init__(cursor)
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1
        if self.commit_count == 2:
            raise RuntimeError("commit acknowledgement lost")


class ContentJobSafetyTest(unittest.TestCase):
    def test_collector_supports_explicit_headless_mode_without_baked_credentials(self):
        args = dataset_collector.build_arg_parser().parse_args(["--headless", "--keyword", "architecture"])

        self.assertTrue(args.headless)
        self.assertEqual(os.environ.get("RANGWAZ_LOGIN_EMAIL", ""), dataset_collector.DEFAULT_LOGIN_EMAIL)
        self.assertEqual(os.environ.get("RANGWAZ_LOGIN_PASSWORD", ""), dataset_collector.DEFAULT_LOGIN_PASSWORD)

    def test_existing_import_user_is_not_mutated(self):
        cursor = _Cursor([{"id": 42}])

        with patch.object(import_images, "IMPORT_AUTHOR_ID", 0), patch.object(
            import_images, "IMPORT_USERNAME", "existing-importer"
        ):
            author_id = import_images.ensure_import_user(_Connection(cursor))

        self.assertEqual(42, author_id)
        self.assertEqual(1, len(cursor.executed))
        self.assertIn("SELECT id FROM app_users", cursor.executed[0][0])
        self.assertIn("status='ACTIVE'", cursor.executed[0][0])
        self.assertNotIn("UPDATE", cursor.executed[0][0].upper())

    def test_inactive_username_import_author_is_rejected(self):
        cursor = _Cursor([])

        with patch.object(import_images, "IMPORT_AUTHOR_ID", 0), patch.object(
            import_images, "IMPORT_USERNAME", "inactive-importer"
        ), self.assertRaises(RuntimeError) as error:
            import_images.ensure_import_user(_Connection(cursor))

        self.assertIn("missing or inactive", str(error.exception))
        self.assertIn("status='ACTIVE'", cursor.executed[0][0])

    def test_resume_result_is_ignored_when_same_named_file_content_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "same-name.jpg"
            previous = b"previous-content"
            image_path.write_bytes(b"replacement-content")
            result_index = {
                import_images.normalized_path_key(image_path): {
                    "ok": True,
                    "path": str(image_path),
                    "hash": import_images.sha256(previous),
                }
            }
            cursor = _Cursor([{"image_id": 9}])

            result = import_images.already_imported_from_result(
                _Connection(cursor), image_path, result_index
            )

        self.assertIsNone(result)
        self.assertEqual([], cursor.executed)

    def test_resume_result_is_used_only_after_current_hash_and_database_match(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "same-content.jpg"
            content = b"unchanged-content"
            image_path.write_bytes(content)
            digest = import_images.sha256(content)
            result_index = {
                import_images.normalized_path_key(image_path): {
                    "ok": True,
                    "path": str(image_path),
                    "hash": digest,
                }
            }
            cursor = _Cursor([{"image_id": 9}])

            result = import_images.already_imported_from_result(
                _Connection(cursor), image_path, result_index
            )

        self.assertEqual("already-recorded", result["status"])
        self.assertEqual(digest, result["hash"])
        self.assertEqual(1, len(cursor.executed))

    def test_linux_resume_keys_preserve_path_case(self):
        upper = Path("A.jpg")
        lower = Path("a.jpg")

        with patch.object(import_images.os, "name", "posix"):
            self.assertNotEqual(
                import_images.normalized_path_key(upper),
                import_images.normalized_path_key(lower),
            )

    def test_collector_does_not_reuse_a_missing_content_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.jsonl").write_text(
                '{"ok":true,"image_url":"https://example.test/a.jpg",'
                '"sha256":"abc","local_path":"/missing/a.jpg"}\n',
                encoding="utf-8",
            )

            index = dataset_collector.load_download_index([root])

        self.assertEqual(1, len(index.seen_candidate_keys))
        self.assertEqual(0, len(index.candidate_keys))
        self.assertNotIn("abc", index.sha256_paths)

    def test_collector_does_not_complete_a_corrupt_manifest_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "images" / "broken.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"not-an-image")
            (root / "manifest.jsonl").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "image_url": "https://i.pinimg.com/originals/aa/bb/cc/image.jpg",
                        "sha256": import_images.sha256(b"not-an-image"),
                        "local_path": str(image_path),
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            index = dataset_collector.load_download_index([root])

        self.assertEqual(1, len(index.seen_candidate_keys))
        self.assertEqual(0, len(index.candidate_keys))

    def test_importer_refuses_to_rebuild_an_unknown_schema(self):
        with patch.object(import_images, "table_exists", return_value=False), self.assertRaises(SystemExit) as error:
            import_images.ensure_database_schema(object())

        self.assertIn("禁止自动建表或删表", str(error.exception))

    def test_import_summary_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "summary.json"
            with patch.object(import_images, "SUMMARY_PATH", target):
                import_images.write_summary({"imported": 3})

            self.assertEqual('{"imported": 3}\n', target.read_text(encoding="utf-8"))
            self.assertFalse(target.with_suffix(".json.tmp").exists())

    def test_empty_import_directory_is_a_successful_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.json"
            with patch.object(import_images, "SUMMARY_PATH", summary), patch.object(
                import_images, "image_files", return_value=[]
            ), patch.object(import_images, "require_dependencies", side_effect=AssertionError("must not connect")):
                import_images.run()

            payload = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(0, payload["imported"])
            self.assertEqual(0, payload["failed"])

    def test_import_limit_is_applied_after_completed_result_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / "{}.jpg".format(index) for index in range(4)]
            for file_path in files:
                file_path.write_bytes(b"placeholder")
            imported_paths = []

            def recorded(_connection, file_path, _result_index):
                if file_path in files[:2]:
                    return {
                        "ok": True,
                        "status": "already-recorded",
                        "hash": import_images.sha256(file_path.read_bytes()),
                    }
                return None

            def imported(_connection, _client, _author_id, file_path):
                imported_paths.append(file_path)
                return {
                    "ok": True,
                    "status": "imported-pending-review",
                    "path": str(file_path),
                    "hash": "ab" * 32,
                }

            with patch.object(import_images, "LIMIT", 2), patch.object(
                import_images, "RESULT_PATH", root / "results.jsonl"
            ), patch.object(import_images, "SUMMARY_PATH", root / "summary.json"), patch.object(
                import_images, "image_files", return_value=files
            ), patch.object(import_images, "minio_client", return_value=object()), patch.object(
                import_images, "ensure_bucket"
            ), patch.object(
                import_images, "connect_mysql", return_value=_Connection(_Cursor())
            ), patch.object(import_images, "ensure_database_schema"), patch.object(
                import_images, "ensure_import_user", return_value=42
            ), patch.object(
                import_images, "already_imported_from_result", side_effect=recorded
            ), patch.object(import_images, "import_one", side_effect=imported), patch.object(
                import_images, "ensure_import_capacity"
            ), patch.object(
                import_images, "archive_processed_file"
            ):
                import_images.run()

            self.assertEqual(files[2:], imported_paths)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(2, summary["attempted"])
            self.assertEqual(2, summary["skipped"])

    def test_import_capacity_fails_when_data_disk_reserve_is_breached(self):
        with patch.object(import_images, "MIN_FREE_BYTES", 100), patch.object(
            import_images, "STORAGE_CHECK_PATH", Path("/data")
        ), patch.object(
            import_images.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=99),
        ), self.assertRaises(RuntimeError):
            import_images.ensure_import_capacity()

    def test_low_capacity_stops_the_batch_after_one_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / "one.jpg", root / "two.jpg"]
            for file_path in files:
                file_path.write_bytes(b"placeholder")

            with patch.object(import_images, "RESULT_PATH", root / "results.jsonl"), patch.object(
                import_images, "SUMMARY_PATH", root / "summary.json"
            ), patch.object(import_images, "image_files", return_value=files), patch.object(
                import_images, "minio_client", return_value=object()
            ), patch.object(import_images, "ensure_bucket"), patch.object(
                import_images, "connect_mysql", return_value=_Connection(_Cursor())
            ), patch.object(import_images, "ensure_database_schema"), patch.object(
                import_images, "ensure_import_user", return_value=42
            ), patch.object(import_images, "already_imported_from_result", return_value=None), patch.object(
                import_images,
                "ensure_import_capacity",
                side_effect=import_images.ImportCapacityError("reserve crossed"),
            ) as capacity, patch.object(import_images, "import_one") as importer, self.assertRaises(SystemExit):
                import_images.run()

            capacity.assert_called_once_with()
            importer.assert_not_called()
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(0, summary["attempted"])
            self.assertEqual(1, summary["failed"])

    def test_confirmed_import_is_atomically_archived_out_of_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "images"
            processed = root / "processed"
            staging.mkdir()
            image_path = staging / "queued.jpg"
            content = b"confirmed-content"
            image_path.write_bytes(content)
            digest = import_images.sha256(content)
            result = {
                "ok": True,
                "status": "duplicate",
                "path": str(image_path),
                "imageId": 9,
                "hash": digest,
            }

            with patch.object(import_images, "RESULT_PATH", root / "results.jsonl"), patch.object(
                import_images, "SUMMARY_PATH", root / "summary.json"
            ), patch.object(import_images, "PROCESSED_DIR", processed), patch.object(
                import_images, "image_files", return_value=[image_path]
            ), patch.object(import_images, "minio_client", return_value=object()), patch.object(
                import_images, "ensure_bucket"
            ), patch.object(import_images, "connect_mysql", return_value=_Connection(_Cursor())), patch.object(
                import_images, "ensure_database_schema"
            ), patch.object(import_images, "ensure_import_user", return_value=42), patch.object(
                import_images, "already_imported_from_result", return_value=None
            ), patch.object(import_images, "ensure_import_capacity"), patch.object(
                import_images, "import_one", return_value=result
            ):
                import_images.run()

            self.assertFalse(image_path.exists())
            archived = processed / "{}.jpg".format(digest)
            self.assertEqual(content, archived.read_bytes())

    def test_import_batch_and_image_limits_cannot_be_raised_above_public_caps(self):
        with patch.dict(os.environ, {"TEST_CONTENT_LIMIT": "501"}), self.assertRaises(SystemExit):
            import_images.env_bounded_positive_int("TEST_CONTENT_LIMIT", 500, 500)
        with patch.dict(os.environ, {"TEST_CONTENT_LIMIT": "0"}), self.assertRaises(SystemExit):
            import_images.env_bounded_positive_int("TEST_CONTENT_LIMIT", 500, 500)

    def test_imported_image_defaults_to_pending_review(self):
        cursor = _Cursor()

        import_images.insert_image_rows(
            _Connection(cursor),
            42,
            Path("checked.jpg"),
            "originals/sha256/aa/aabb.jpg",
            "thumbs/sha256/aa/aabb.jpg",
            640,
            480,
            1234,
            "aabb",
            "image/jpeg",
        )

        sql, _ = cursor.executed[0]
        self.assertIn("'PENDING_REVIEW'", sql)
        self.assertNotIn("'PUBLISHED'", sql)

    def test_object_keys_are_deterministic_from_content_hash(self):
        first = import_images.object_keys("ab" * 32, ".jpg")
        second = import_images.object_keys("ab" * 32, ".jpg")

        self.assertEqual(first, second)
        self.assertIn("ab" * 32, first[0])
        self.assertIn("ab" * 32, first[1])

    def test_ambiguous_database_commit_never_deletes_uploaded_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "checked.jpg"
            image_path.write_bytes(b"image")
            result_path = root / "results.jsonl"
            summary_path = root / "summary.json"
            client = SimpleNamespace(remove_object=Mock())
            connection = _CommitUncertainConnection(_Cursor())
            imported = {
                "ok": True,
                "status": "imported",
                "path": str(image_path),
                "imageId": 9,
                "hash": "ab" * 32,
                "_uploadedObjectKeys": ["original", "thumb"],
            }

            with patch.object(import_images, "RESULT_PATH", result_path), patch.object(
                import_images, "SUMMARY_PATH", summary_path
            ), patch.object(import_images, "image_files", return_value=[image_path]), patch.object(
                import_images, "minio_client", return_value=client
            ), patch.object(import_images, "ensure_bucket"), patch.object(
                import_images, "connect_mysql", return_value=connection
            ), patch.object(import_images, "ensure_database_schema"), patch.object(
                import_images, "ensure_import_user", return_value=42
            ), patch.object(import_images, "import_one", return_value=imported), self.assertRaises(SystemExit):
                import_images.run()

            client.remove_object.assert_not_called()
            self.assertTrue(image_path.exists())

    def test_collector_enforces_response_byte_limit(self):
        response = io.BytesIO(b"x" * 11)
        response.headers = {}

        with self.assertRaises(ValueError):
            dataset_collector.read_response_limited(response, 10)

    def test_collector_enforces_decoded_pixel_limit(self):
        payload = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(payload, format="PNG")

        with self.assertRaises(ValueError):
            dataset_collector.validate_downloaded_image(payload.getvalue(), 399)

    def test_collector_rejects_redirect_to_disallowed_image_host(self):
        with tempfile.TemporaryDirectory() as directory:
            response = io.BytesIO(b"must-not-be-decoded")
            response.headers = {"Content-Type": "image/jpeg"}
            response.geturl = lambda: "http://127.0.0.1/private.jpg"
            candidate = dataset_collector.ImageCandidate(
                image_url="https://i.pinimg.com/originals/aa/bb/cc/image.jpg"
            )

            with patch.object(dataset_collector, "urlopen", return_value=response), patch.object(
                dataset_collector,
                "validate_downloaded_image",
                side_effect=AssertionError("disallowed redirect must not be decoded"),
            ):
                result = dataset_collector.download_one(
                    1,
                    candidate,
                    Path(directory),
                    dataset_collector.CollectorConfig(pinimg_only=True),
                    {},
                )

        self.assertFalse(result.ok)
        self.assertIn("redirected to disallowed image URL", result.error)

    def test_collector_rejects_disallowed_fallback_before_request(self):
        candidate = dataset_collector.ImageCandidate(
            image_url="http://127.0.0.1/private.jpg"
        )

        with tempfile.TemporaryDirectory() as directory, patch.object(
            dataset_collector,
            "urlopen",
            side_effect=AssertionError("disallowed URL must not be requested"),
        ):
            result = dataset_collector.download_one(
                1,
                candidate,
                Path(directory),
                dataset_collector.CollectorConfig(pinimg_only=True),
                {},
            )

        self.assertFalse(result.ok)
        self.assertIn("disallowed image URL", result.error)

    def test_collector_repairs_existing_corrupt_download_atomically(self):
        payload = io.BytesIO()
        Image.new("RGB", (8, 6), "blue").save(payload, format="PNG")
        data = payload.getvalue()
        digest = dataset_collector.hashlib.sha256(data).hexdigest()
        candidate = dataset_collector.ImageCandidate(
            image_url="https://i.pinimg.com/originals/aa/bb/cc/image.png"
        )

        with tempfile.TemporaryDirectory() as directory:
            images_dir = Path(directory)
            target = images_dir / "{}.png".format(digest[:20])
            target.write_bytes(b"corrupt-existing-file")
            response = io.BytesIO(data)
            response.headers = {"Content-Type": "image/png"}
            response.geturl = lambda: candidate.image_url
            replace_calls = []
            real_replace = dataset_collector.os.replace

            def record_replace(source, destination):
                replace_calls.append((Path(source), Path(destination)))
                return real_replace(source, destination)

            with patch.object(dataset_collector, "urlopen", return_value=response), patch.object(
                dataset_collector.os, "replace", side_effect=record_replace
            ), patch.object(dataset_collector.os, "fsync", wraps=dataset_collector.os.fsync) as fsync:
                result = dataset_collector.download_one(
                    1,
                    candidate,
                    images_dir,
                    dataset_collector.CollectorConfig(pinimg_only=True, request_delay=0),
                    {},
                )

            self.assertTrue(result.ok)
            self.assertEqual("repaired", result.status)
            self.assertEqual(data, target.read_bytes())
            self.assertGreaterEqual(fsync.call_count, 1)
            self.assertEqual(1, len(replace_calls))
            self.assertEqual(target.parent, replace_calls[0][0].parent)
            self.assertEqual(target, replace_calls[0][1])
            self.assertEqual([], list(images_dir.glob(".*.tmp")))

    def test_collector_validates_existing_download_before_reuse(self):
        payload = io.BytesIO()
        Image.new("RGB", (8, 6), "green").save(payload, format="PNG")
        data = payload.getvalue()
        digest = dataset_collector.hashlib.sha256(data).hexdigest()
        candidate = dataset_collector.ImageCandidate(
            image_url="https://i.pinimg.com/originals/aa/bb/cc/image.png"
        )

        with tempfile.TemporaryDirectory() as directory:
            images_dir = Path(directory)
            target = images_dir / "{}.png".format(digest[:20])
            target.write_bytes(data)
            response = io.BytesIO(data)
            response.headers = {"Content-Type": "image/png"}
            response.geturl = lambda: candidate.image_url

            with patch.object(dataset_collector, "urlopen", return_value=response), patch.object(
                dataset_collector, "atomic_write_download", side_effect=AssertionError("valid file must be reused")
            ):
                result = dataset_collector.download_one(
                    1,
                    candidate,
                    images_dir,
                    dataset_collector.CollectorConfig(pinimg_only=True, request_delay=0),
                    {},
                )

            self.assertTrue(result.ok)
            self.assertEqual("exists", result.status)

    def test_headless_login_gate_fails_closed_even_with_zero_wait(self):
        with patch.object(
            dataset_collector,
            "detect_login_gate",
            return_value={"gated": True, "url": "https://example.test/login"},
        ), patch.object(dataset_collector.time, "sleep"), self.assertRaises(RuntimeError):
            dataset_collector.wait_for_login_if_needed(
                object(),
                0,
                "",
                "",
                lambda _: None,
                fail_on_login_gate=True,
            )

    def test_login_gate_detection_failure_is_fatal_even_in_visible_mode(self):
        with patch.object(
            dataset_collector,
            "detect_login_gate",
            side_effect=RuntimeError("page changed"),
        ), patch.object(dataset_collector.time, "sleep"), self.assertRaises(RuntimeError):
            dataset_collector.wait_for_login_if_needed(
                object(),
                0,
                "operator@example.invalid",
                "test-only-placeholder",
                lambda _: None,
                fail_on_login_gate=False,
            )

    def test_visible_login_gate_cannot_continue_after_zero_wait(self):
        with patch.object(
            dataset_collector,
            "detect_login_gate",
            return_value={"gated": True, "url": "https://example.test/challenge"},
        ), patch.object(dataset_collector.time, "sleep"), self.assertRaises(RuntimeError):
            dataset_collector.wait_for_login_if_needed(
                object(),
                0,
                "",
                "",
                lambda _: None,
                fail_on_login_gate=False,
            )

    def test_gate_detector_covers_captcha_2fa_and_risk_control(self):
        page = Mock()
        page.evaluate.return_value = {"gated": False}

        dataset_collector.detect_login_gate(page)

        detector_source = page.evaluate.call_args.args[0].lower()
        self.assertIn("captcha", detector_source)
        self.assertIn("two-factor", detector_source)
        self.assertIn("风控", detector_source)

    def test_pipeline_retries_preexisting_search_dirty_and_retains_it_on_failure(self):
        root = Path(__file__).resolve().parents[2]
        script = (root / "ops" / "jobs" / "run-content-pipeline.sh").read_text(encoding="utf-8")

        self.assertIn("search-dirty", script)
        self.assertNotIn("mark_search_dirty", script)
        retry_condition = 'if is_true "$SEARCH_REINDEX_ENABLED" && [[ -e $SEARCH_DIRTY_FILE ]]'
        self.assertIn(retry_condition, script)
        reindex_position = script.index('"$REPO_ROOT/tools/reindex_search_es.py" --confirm-promote')
        clear_position = script.index("\n  clear_search_dirty\n")
        self.assertGreater(clear_position, reindex_position)
        self.assertNotIn("\n  clear_search_dirty\n", script[:reindex_position])

    def test_content_unit_uses_dedicated_user_and_minimal_environment(self):
        root = Path(__file__).resolve().parents[2]
        unit = (root / "ops" / "jobs" / "systemd" / "vibelo-content-ingest.service").read_text(
            encoding="utf-8"
        )

        self.assertIn("User=vibelo-jobs", unit)
        self.assertIn("RuntimeDirectory=vibelo-content-jobs", unit)
        self.assertIn("/run/vibelo-content-jobs/content.lock", unit)
        self.assertNotIn("/run/vibelo-jobs/content.lock", unit)
        self.assertIn("ReadWritePaths=/data/vibelo-ingest /run/vibelo-content-jobs", unit)
        self.assertIn("/usr/bin/bash /opt/vibelo/ops/jobs/run-content-pipeline.sh", unit)
        self.assertNotIn("EnvironmentFile=/opt/vibelo/.env.public", unit)

        installer = (root / "ops" / "jobs" / "install-content-timer.sh").read_text(encoding="utf-8")
        self.assertIn("ensure_service_identity", installer)
        self.assertIn("prepare_minimal_environment", installer)
        self.assertIn("publish_minimal_environment", installer)
        self.assertIn("VIBELO_DB_PASSWORD", installer)
        self.assertIn("MINIO_SECRET_KEY", installer)
        self.assertNotIn("ALIYUN_SMS_ACCESS_KEY", installer)
        self.assertNotIn("APP_AUTH_TOKEN_SECRET", installer)
        self.assertNotIn("APP_MODERATION_TOKEN", installer)
        self.assertIn('done <"$template" >"$TEMP_ENV"', installer)
        self.assertIn('mv -f -- "$TEMP_ENV" "$JOB_ENV"', installer)
        prepare_position = installer.rindex("\nprepare_minimal_environment\n")
        unit_position = installer.index(
            'install -m 0644 "$REPO_ROOT/ops/jobs/systemd/vibelo-content-ingest.service"'
        )
        publish_position = installer.rindex("\npublish_minimal_environment\n")
        self.assertLess(prepare_position, unit_position)
        self.assertLess(unit_position, publish_position)
        self.assertIn("ENV_PUBLISH_STARTED=true", installer)
        self.assertIn("$ENV_PUBLISH_STARTED == true", installer)
        self.assertIn('systemctl is-enabled "$TIMER_UNIT"', installer)
        self.assertIn('systemctl disable --now "$TIMER_UNIT"', installer)
        self.assertIn("restore_timer_before_publish", installer)
        self.assertNotIn("chown -R", installer)
        self.assertIn("--no-dereference", installer)
        self.assertIn("-xdev", installer)
        self.assertIn("reject_task_tree_symlinks", installer)
        self.assertIn("quiesce_content_timer", installer)
        self.assertIn("TUNING_KEYS=(", installer)
        tuning_block = installer.split("TUNING_KEYS=(", 1)[1].split(")", 1)[0]
        self.assertNotIn("VIBELO_CONTENT_JOB_ROOT", tuning_block)
        self.assertNotIn("VIBELO_MINIO_ENDPOINT", tuning_block)
        self.assertNotIn("VIBELO_ES_URL", tuning_block)
        self.assertIn('primary_group=$(id -gn "$SERVICE_USER")', installer)
        self.assertIn("root|docker|sudo|wheel", installer)
        self.assertNotIn('awk -v key="$key" -v replacement="$replacement"', installer)

        preflight = (root / "ops" / "jobs" / "content-job-preflight.sh").read_text(encoding="utf-8")
        self.assertIn("SELECT 1, CURRENT_USER()", preflight)
        self.assertIn("bucket_exists", preflight)
        self.assertIn("秘密未显示", preflight)

    def test_existing_vector_collection_dimension_must_match(self):
        field = SimpleNamespace(name="embedding", params={"dim": 256})
        collection = SimpleNamespace(schema=SimpleNamespace(fields=[field]), indexes=[])

        with self.assertRaises(RuntimeError) as error:
            vectorize_images.validate_collection(collection)

        self.assertIn("dimension 256 does not match 512", str(error.exception))

    def test_existing_vector_collection_rejects_non_cosine_metric(self):
        field = SimpleNamespace(name="embedding", params={"dim": 512})
        index = SimpleNamespace(field_name="embedding", params={"metric_type": "L2"})
        collection = SimpleNamespace(schema=SimpleNamespace(fields=[field]), indexes=[index])

        with self.assertRaises(RuntimeError) as error:
            vectorize_images.validate_collection(collection)

        self.assertIn("must be HNSW/COSINE", str(error.exception))

    def test_vector_full_coverage_marker_is_atomic_and_artifact_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "state" / "ready.json"
            with patch.object(vectorize_images, "READY_MARKER_PATH", marker):
                vectorize_images.write_ready_marker({17})

            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(vectorize_images.MODEL_NAME, payload["model"])
            self.assertEqual(vectorize_images.PROJECTION_VERSION, payload["projectionVersion"])
            self.assertEqual(vectorize_images.VECTOR_VERSION, payload["vectorVersion"])
            self.assertEqual(vectorize_images.MILVUS_COLLECTION, payload["collection"])
            self.assertEqual(1, payload["ready"])
            self.assertEqual(1, payload["entities"])
            self.assertEqual(vectorize_images.id_set_sha256({17}), payload["idSetSha256"])
            self.assertFalse(marker.with_name("ready.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
