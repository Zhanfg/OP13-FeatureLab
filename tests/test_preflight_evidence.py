# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from featurelab.preflight_archive import verify_preflight_archive
from featurelab.preflight_evidence import classify_preflight_evidence
from preflight_fixture import base_files, create_archive


class PreflightEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def classify(self, **kwargs):
        archive, sidecar = create_archive(self.root, files=base_files(**kwargs))
        return classify_preflight_evidence(verify_preflight_archive(archive, sidecar))

    def test_ready_evidence(self) -> None:
        result = self.classify()
        self.assertEqual(result.verdict, "READY_FOR_CONTROLLED_VALIDATION")
        self.assertFalse(result.blockers)

    def test_wrong_device_blocks(self) -> None:
        result = self.classify(device="OTHER")
        self.assertEqual(result.verdict, "BLOCKED")
        self.assertIn("device.unsupported_product", {item.code for item in result.blockers})

    def test_selinux_permissive_blocks(self) -> None:
        result = self.classify(selinux="PERMISSIVE")
        self.assertIn("security.selinux_not_enforcing", {item.code for item in result.blockers})

    def test_required_ksu_query_failure_blocks(self) -> None:
        result = self.classify(required_ok=False)
        self.assertIn("kernelsu.required_query_failed", {item.code for item in result.blockers})

    def test_active_known_overlay_blocks(self) -> None:
        mount = (
            "50 1 0:50 /data/adb/modules/safe.module/system/etc /system/etc rw - none none rw\n"
        )
        result = self.classify(mountinfo=mount)
        self.assertEqual(result.overlay_conflicts[0].inventory_state, "active")
        self.assertIn("modules.protected_overlay", {item.code for item in result.blockers})

    def test_unknown_overlay_blocks(self) -> None:
        mount = (
            "50 1 0:50 /data/adb/modules/unknown.module/system/etc /system/etc rw - none none rw\n"
        )
        result = self.classify(mountinfo=mount)
        self.assertEqual(result.overlay_conflicts[0].inventory_state, "unknown-inventory")

    def test_namespace_difference_warns(self) -> None:
        result = self.classify(namespace="DIFFERENT")
        self.assertEqual(result.verdict, "READY_FOR_CONTROLLED_VALIDATION")
        self.assertIn("mount.namespace_differs", {item.code for item in result.warnings})

    def test_kernel_and_verified_boot_warnings(self) -> None:
        result = self.classify(tainted="512", verified_boot="orange", optional_ok=False)
        codes = {item.code for item in result.warnings}
        self.assertIn("kernel.tainted", codes)
        self.assertIn("boot.verified_state_not_green", codes)
        self.assertIn("kernelsu.optional_query_failed", codes)


if __name__ == "__main__":
    unittest.main()
