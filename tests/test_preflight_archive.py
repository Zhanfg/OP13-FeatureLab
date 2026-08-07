# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from featurelab.preflight_archive import PreflightArchiveError, verify_preflight_archive
from preflight_fixture import base_files, create_archive


class PreflightArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_archive(self) -> None:
        archive, sidecar = create_archive(self.root)
        verified = verify_preflight_archive(archive, sidecar)
        self.assertEqual(verified.read_text("summary.tsv").splitlines()[0], "field\tvalue")

    def test_sidecar_mismatch(self) -> None:
        archive, sidecar = create_archive(self.root)
        sidecar.write_text("0" * 64 + f"  {archive.name}\n")
        with self.assertRaisesRegex(PreflightArchiveError, "external SHA-256"):
            verify_preflight_archive(archive, sidecar)

    def test_path_traversal_rejected(self) -> None:
        archive, sidecar = create_archive(self.root, traversal=True)
        with self.assertRaisesRegex(PreflightArchiveError, "unsafe tar member"):
            verify_preflight_archive(archive, sidecar)

    def test_duplicate_member_rejected(self) -> None:
        archive, sidecar = create_archive(self.root, duplicate="summary.tsv")
        with self.assertRaisesRegex(PreflightArchiveError, "duplicate tar member"):
            verify_preflight_archive(archive, sidecar)

    def test_symlink_rejected(self) -> None:
        archive, sidecar = create_archive(self.root, symlink="link")
        with self.assertRaisesRegex(PreflightArchiveError, "unsupported tar member"):
            verify_preflight_archive(archive, sidecar)

    def test_member_count_limit(self) -> None:
        archive, sidecar = create_archive(self.root, member_count=20)
        with self.assertRaisesRegex(PreflightArchiveError, "members"):
            verify_preflight_archive(archive, sidecar, max_members=10)

    def test_file_size_limit(self) -> None:
        archive, sidecar = create_archive(self.root, large_size=128)
        with self.assertRaisesRegex(PreflightArchiveError, "size limit"):
            verify_preflight_archive(archive, sidecar, max_file_size=64)

    def test_internal_manifest_mismatch(self) -> None:
        files = base_files()
        files["summary.tsv"] += b"tamper\n"
        archive, sidecar = create_archive(self.root, files=files, corrupt_manifest=True)
        with self.assertRaisesRegex(PreflightArchiveError, "manifest hash mismatch"):
            verify_preflight_archive(archive, sidecar)


if __name__ == "__main__":
    unittest.main()
