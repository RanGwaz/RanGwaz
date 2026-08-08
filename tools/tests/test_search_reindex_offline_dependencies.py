from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
VERSION = "1.1.2"
WHEEL_NAME = "pymysql-1.1.2-py3-none-any.whl"
WHEEL_SIZE = "45300"
WHEEL_SHA256 = "e6b1d89711dd51f8f74b1631fe08f039e7d76cf67a42a323d3178f0f25762ed9"


class OfflineSearchDependencyTest(unittest.TestCase):
    def text(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_requirement_is_exact_and_hash_locked(self):
        requirement = self.text("tools/requirements_search_reindex.txt")
        self.assertIn("PyMySQL==" + VERSION, requirement)
        self.assertIn("--hash=sha256:" + WHEEL_SHA256, requirement)

    def test_prepare_and_install_scripts_share_fixed_artifact_identity(self):
        prepare = self.text("ops/public/Prepare-SearchReindexDependencies.ps1")
        install = self.text("ops/public/install-search-reindex-dependencies.sh")
        for expected in (WHEEL_NAME, WHEEL_SIZE, WHEEL_SHA256):
            self.assertIn(expected, prepare)
            self.assertIn(expected, install)

    def test_ecs_installer_forbids_package_index_access(self):
        install = self.text("ops/public/install-search-reindex-dependencies.sh")
        self.assertIn("PIP_NO_INDEX=1", install)
        self.assertIn("--no-index", install)
        self.assertIn("--no-deps", install)
        self.assertIn("--require-hashes", install)
        self.assertNotIn("http://", install)
        self.assertNotIn("https://", install)

    def test_ecs_installer_publishes_only_a_fully_verified_temporary_venv(self):
        install = self.text("ops/public/install-search-reindex-dependencies.sh")
        self.assertIn("mktemp -d", install)
        self.assertIn('python3 -m venv "$temporary_venv"', install)
        self.assertIn('mv -T -- "$temporary_venv" "$VENV_PATH"', install)
        self.assertNotIn('python3 -m venv "$VENV_PATH"', install)


if __name__ == "__main__":
    unittest.main()
