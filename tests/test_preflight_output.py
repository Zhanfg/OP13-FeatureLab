# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from featurelab.preflight import PreflightAnalysisError, analyze_preflight_archive
from preflight_fixture import base_files, create_archive


class PreflightOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.outputs = self.root / "outputs"
        self.inputs.mkdir()
        self.outputs.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_minimized_outputs(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        output = self.outputs / "analysis.private"
        result = analyze_preflight_archive(archive, sidecar, output)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            sorted(path.name for path in output.iterdir()),
            ["analysis.json", "compatibility-getprop.private.txt", "preflight-inputs.sha256"],
        )
        analysis = json.loads((output / "analysis.json").read_text())
        self.assertTrue(analysis["not_flash_ready"])
        self.assertNotIn("OnePlus/PJZ110", (output / "analysis.json").read_text())

    def test_existing_output_is_replaced(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        output = self.outputs / "analysis.private"
        output.mkdir()
        (output / "old.txt").write_text("old")
        analyze_preflight_archive(archive, sidecar, output)
        self.assertFalse((output / "old.txt").exists())

    def test_analysis_failure_preserves_existing_output(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        output = self.outputs / "analysis.private"
        output.mkdir()
        marker = output / "old.txt"
        marker.write_text("old")
        sidecar.write_text("0" * 64 + f"  {archive.name}\n")
        with self.assertRaises(PreflightAnalysisError):
            analyze_preflight_archive(archive, sidecar, output)
        self.assertEqual(marker.read_text(), "old")

    def test_output_parent_must_exist(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        with self.assertRaisesRegex(PreflightAnalysisError, "parent"):
            analyze_preflight_archive(archive, sidecar, self.outputs / "missing" / "out")

    def test_output_parent_symlink_rejected(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        real = self.outputs / "real"
        real.mkdir()
        link = self.outputs / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(PreflightAnalysisError, "parent"):
            analyze_preflight_archive(archive, sidecar, link / "out")

    def test_output_symlink_rejected(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        real = self.outputs / "real"
        real.mkdir()
        output = self.outputs / "link"
        output.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(PreflightAnalysisError, "real directory"):
            analyze_preflight_archive(archive, sidecar, output)

    def test_output_overlap_input_rejected(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        with self.assertRaisesRegex(PreflightAnalysisError, "overlap"):
            analyze_preflight_archive(archive, sidecar, archive / "analysis")

    def test_commit_failure_restores_old_output(self) -> None:
        archive, sidecar = create_archive(self.inputs)
        output = self.outputs / "analysis.private"
        output.mkdir()
        marker = output / "old.txt"
        marker.write_text("old")
        calls = 0
        real_replace = os.replace

        def failing_replace(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected commit failure")
            return real_replace(src, dst)

        with self.assertRaisesRegex(PreflightAnalysisError, "transaction"):
            analyze_preflight_archive(archive, sidecar, output, replace=failing_replace)
        self.assertEqual(marker.read_text(), "old")


if __name__ == "__main__":
    unittest.main()
