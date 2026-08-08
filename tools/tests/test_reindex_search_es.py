from __future__ import annotations

import argparse
import os
import unittest
from contextlib import nullcontext
from unittest import mock

from tools import reindex_search_es as reindex


class FingerprintTest(unittest.TestCase):
    def build(self, documents):
        builder = reindex.DatasetFingerprintBuilder()
        for document_id, source in documents:
            builder.add(document_id, source)
        return builder.finish()

    def test_canonical_fingerprint_ignores_json_key_order(self):
        first = self.build([("1", {"title": "one", "id": 1})])
        second = self.build([("1", {"id": 1, "title": "one"})])
        self.assertEqual(first, second)

    def test_content_change_keeps_collection_fingerprint_but_changes_content(self):
        first = self.build([("1", {"id": 1, "title": "one"})])
        second = self.build([("1", {"id": 1, "title": "changed"})])
        self.assertEqual(first.collection_fingerprint, second.collection_fingerprint)
        self.assertNotEqual(first.content_fingerprint, second.content_fingerprint)


class ConsistentSnapshotTest(unittest.TestCase):
    def test_snapshot_uses_repeatable_read_and_read_only_consistent_snapshot(self):
        cursor = mock.MagicMock()
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        reindex.begin_consistent_snapshot(conn)

        self.assertEqual(
            [
                mock.call("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ"),
                mock.call("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"),
            ],
            cursor.execute.call_args_list,
        )

    def test_snapshot_context_rolls_back_and_closes(self):
        conn = mock.MagicMock()
        with mock.patch.object(reindex, "connect_mysql", return_value=conn) as connect:
            with reindex.consistent_snapshot(mock.sentinel.args) as yielded:
                self.assertIs(conn, yielded)

        connect.assert_called_once_with(mock.sentinel.args, autocommit=False)
        conn.rollback.assert_called_once_with()
        conn.close.assert_called_once_with()


class SearchReindexSafetyTest(unittest.TestCase):
    def args(self, **overrides):
        values = {
            "mysql_host": "rds.internal",
            "mysql_port": 3306,
            "mysql_database": "rangwaz_image_dev",
            "mysql_user": "vibelo_app",
            "mysql_password": "secret",
            "es_url": "http://elasticsearch:9200",
            "es_index": "rangwaz-images",
            "batch_size": 500,
            "timeout_seconds": 30,
            "limit": 0,
            "no_recreate": False,
            "replace_conflicting_index": False,
            "dry_run": False,
            "confirm_promote": True,
            "lock_name": "vibelo-search-reindex",
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def fingerprint(self, content="a", collection="ids", count=2):
        return reindex.DatasetFingerprint(count, collection, content)

    def test_public_database_environment_names_are_supported(self):
        with mock.patch.dict(
            os.environ,
            {
                "VIBELO_DB_HOST": "rds.internal",
                "VIBELO_DB_PORT": "3307",
                "VIBELO_DB_NAME": "vibelo",
                "VIBELO_DB_USER": "vibelo_app",
                "VIBELO_DB_PASSWORD": "secret",
            },
            clear=True,
        ):
            self.assertEqual("rds.internal", reindex._env_value("VIBELO_MYSQL_HOST", "VIBELO_DB_HOST", "127.0.0.1"))
            self.assertEqual("3307", reindex._env_value("VIBELO_MYSQL_PORT", "VIBELO_DB_PORT", "3306"))
            self.assertEqual("vibelo", reindex._env_value("VIBELO_MYSQL_DATABASE", "VIBELO_DB_NAME", "default"))
            self.assertEqual("vibelo_app", reindex._env_value("VIBELO_MYSQL_USER", "VIBELO_DB_USER", "default"))
            self.assertEqual("secret", reindex._env_value("VIBELO_MYSQL_PASSWORD", "VIBELO_DB_PASSWORD", ""))

    def test_success_certifies_then_promotes_then_verifies_unique_alias(self):
        events = []
        source = self.fingerprint()
        lock_conn = mock.MagicMock()
        es = mock.Mock()
        certificates = {}

        es.count.side_effect = [2, 2]
        es.fingerprint.side_effect = [source, source]
        es.alias_indices.return_value = ["rangwaz-images-candidate"]
        es.swap_alias.side_effect = lambda *args: events.append("swap") or []

        def create(index):
            events.append("create")
            es.alias_indices.return_value = [index]

        def write_certificate(index, certificate):
            events.append("certificate")
            certificates[index] = certificate

        es.create_index.side_effect = create
        es.write_certificate.side_effect = write_certificate
        es.certificates.side_effect = lambda _: dict(certificates)

        with mock.patch.object(reindex, "Elasticsearch", return_value=es), \
                mock.patch.object(reindex, "connect_mysql", return_value=lock_conn), \
                mock.patch.object(reindex, "consistent_snapshot", side_effect=[nullcontext(object()), nullcontext(object())]), \
                mock.patch.object(reindex, "acquire_reindex_lock", side_effect=lambda *_: events.append("lock")), \
                mock.patch.object(reindex, "release_reindex_lock", side_effect=lambda *_: events.append("unlock")), \
                mock.patch.object(reindex, "count_published", side_effect=[2, 2]), \
                mock.patch.object(reindex, "scan_snapshot", side_effect=[source, source]):
            self.assertEqual(0, reindex.run_reindex(self.args()))

        self.assertLess(events.index("certificate"), events.index("swap"))
        self.assertEqual("lock", events[0])
        self.assertEqual("unlock", events[-1])
        certificate = next(iter(certificates.values()))
        self.assertEqual("v1", certificate["schema"])
        self.assertEqual("verified", certificate["status"])
        self.assertEqual(2, certificate["published_count"])
        self.assertEqual(source.content_fingerprint, certificate["source_fingerprint"])
        self.assertEqual(source.collection_fingerprint, certificate["collection_fingerprint"])

    def test_candidate_content_mismatch_never_certifies_or_promotes(self):
        source = self.fingerprint(content="source")
        candidate = self.fingerprint(content="candidate")
        lock_conn = mock.MagicMock()
        es = mock.Mock()
        es.count.return_value = 2
        es.fingerprint.return_value = candidate

        with mock.patch.object(reindex, "Elasticsearch", return_value=es), \
                mock.patch.object(reindex, "connect_mysql", return_value=lock_conn), \
                mock.patch.object(reindex, "consistent_snapshot", return_value=nullcontext(object())), \
                mock.patch.object(reindex, "acquire_reindex_lock"), \
                mock.patch.object(reindex, "release_reindex_lock"), \
                mock.patch.object(reindex, "count_published", return_value=2), \
                mock.patch.object(reindex, "scan_snapshot", return_value=source):
            with self.assertRaises(SystemExit):
                reindex.run_reindex(self.args())

        es.write_certificate.assert_not_called()
        es.swap_alias.assert_not_called()

    def test_changed_live_source_fingerprint_never_certifies_or_promotes(self):
        source = self.fingerprint(content="before")
        live = self.fingerprint(content="after")
        lock_conn = mock.MagicMock()
        es = mock.Mock()
        es.count.return_value = 2
        es.fingerprint.return_value = source

        with mock.patch.object(reindex, "Elasticsearch", return_value=es), \
                mock.patch.object(reindex, "connect_mysql", return_value=lock_conn), \
                mock.patch.object(reindex, "consistent_snapshot", side_effect=[nullcontext(object()), nullcontext(object())]), \
                mock.patch.object(reindex, "acquire_reindex_lock"), \
                mock.patch.object(reindex, "release_reindex_lock"), \
                mock.patch.object(reindex, "count_published", side_effect=[2, 2]), \
                mock.patch.object(reindex, "scan_snapshot", side_effect=[source, live]):
            with self.assertRaises(SystemExit):
                reindex.run_reindex(self.args())

        es.write_certificate.assert_not_called()
        es.swap_alias.assert_not_called()

    def test_bulk_failure_never_certifies_or_promotes_and_releases_lock(self):
        lock_conn = mock.MagicMock()
        es = mock.Mock()
        release = mock.Mock()

        with mock.patch.object(reindex, "Elasticsearch", return_value=es), \
                mock.patch.object(reindex, "connect_mysql", return_value=lock_conn), \
                mock.patch.object(reindex, "consistent_snapshot", return_value=nullcontext(object())), \
                mock.patch.object(reindex, "acquire_reindex_lock"), \
                mock.patch.object(reindex, "release_reindex_lock", release), \
                mock.patch.object(reindex, "count_published", return_value=1), \
                mock.patch.object(reindex, "scan_snapshot", side_effect=SystemExit("bulk failed")):
            with self.assertRaises(SystemExit):
                reindex.run_reindex(self.args())

        es.write_certificate.assert_not_called()
        es.swap_alias.assert_not_called()
        release.assert_called_once_with(lock_conn, "vibelo-search-reindex")

    def test_limit_cannot_write_or_promote(self):
        with mock.patch.object(reindex, "connect_mysql") as connect:
            with self.assertRaises(SystemExit):
                reindex.run_reindex(self.args(limit=10))
        connect.assert_not_called()

    def test_promotion_is_disabled_without_explicit_confirmation(self):
        with mock.patch.object(reindex, "connect_mysql") as connect:
            with self.assertRaises(SystemExit):
                reindex.run_reindex(self.args(confirm_promote=False))
        connect.assert_not_called()

    def test_dry_run_with_limit_never_writes_or_promotes(self):
        source = self.fingerprint(count=1)
        lock_conn = mock.MagicMock()
        es = mock.Mock()

        with mock.patch.object(reindex, "Elasticsearch", return_value=es), \
                mock.patch.object(reindex, "connect_mysql", return_value=lock_conn), \
                mock.patch.object(reindex, "consistent_snapshot", return_value=nullcontext(object())), \
                mock.patch.object(reindex, "acquire_reindex_lock"), \
                mock.patch.object(reindex, "release_reindex_lock"), \
                mock.patch.object(reindex, "count_published", return_value=2), \
                mock.patch.object(reindex, "scan_snapshot", return_value=source):
            self.assertEqual(0, reindex.run_reindex(self.args(limit=1, dry_run=True, confirm_promote=False)))

        es.create_index.assert_not_called()
        es.write_certificate.assert_not_called()
        es.swap_alias.assert_not_called()


class AtomicAliasSwapTest(unittest.TestCase):
    def test_conflicting_concrete_index_is_removed_in_same_atomic_alias_request(self):
        es = reindex.Elasticsearch("http://elasticsearch:9200", "rangwaz-images", 30)
        es.alias_indices = mock.Mock(return_value=[])
        es.status = mock.Mock(return_value=200)
        es.json_request = mock.Mock(return_value={})

        es.swap_alias("rangwaz-images", "rangwaz-images-v2", True)

        es.json_request.assert_called_once_with(
            "POST",
            "/_aliases",
            {
                "actions": [
                    {"remove_index": {"index": "rangwaz-images"}},
                    {"add": {"index": "rangwaz-images-v2", "alias": "rangwaz-images"}},
                ]
            },
        )

    def test_post_promotion_gate_rejects_alias_with_more_than_one_index(self):
        es = mock.Mock()
        es.alias_indices.return_value = ["candidate", "unexpected"]
        with self.assertRaises(SystemExit):
            reindex.verify_promoted_alias(
                es,
                "rangwaz-images",
                "candidate",
                reindex.DatasetFingerprint(1, "ids", "content"),
                {"schema": "v1"},
                500,
            )
        es.count.assert_not_called()


if __name__ == "__main__":
    unittest.main()
