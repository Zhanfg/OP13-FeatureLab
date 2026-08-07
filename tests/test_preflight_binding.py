# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from featurelab.assembly_policy import AssemblyError
from featurelab.assembly_preflight import (
    validate_preflight_analysis,
    write_preflight_binding,
)


class PreflightBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.properties = {
            "ro.product.device": "PJZ110",
            "ro.product.model": "OnePlus 13",
        }
        hashes = {
            key: hashlib.sha256(value.encode()).hexdigest()
            for key, value in self.properties.items()
        }
        self.analysis = self.root / "analysis.json"
        self.payload = {
            "format": 1,
            "verdict": "READY_FOR_CONTROLLED_VALIDATION",
            "not_flash_ready": True,
            "blockers": [],
            "archive": {
                "sha256": "a" * 64,
                "sidecar_sha256": "b" * 64,
            },
            "device": {"property_sha256": hashes},
        }
        self._write()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self) -> None:
        self.analysis.write_text(json.dumps(self.payload), encoding="utf-8")

    def test_valid_analysis_returns_minimized_binding(self) -> None:
        binding = validate_preflight_analysis(self.analysis, self.properties)
        self.assertEqual(
            binding["verdict"],
            "READY_FOR_CONTROLLED_VALIDATION",
        )
        self.assertTrue(binding["not_flash_ready"])
        text = json.dumps(binding)
        self.assertNotIn("PJZ110", text)
        self.assertNotIn("OnePlus 13", text)

    def test_blocked_verdict_is_rejected(self) -> None:
        self.payload["verdict"] = "BLOCKED"
        self._write()
        with self.assertRaises(AssemblyError):
            validate_preflight_analysis(self.analysis, self.properties)

    def test_blockers_are_rejected(self) -> None:
        self.payload["blockers"] = [{"code": "x"}]
        self._write()
        with self.assertRaises(AssemblyError):
            validate_preflight_analysis(self.analysis, self.properties)

    def test_property_hash_mismatch_is_rejected(self) -> None:
        self.payload["device"]["property_sha256"][
            "ro.product.device"
        ] = "c" * 64
        self._write()
        with self.assertRaises(AssemblyError):
            validate_preflight_analysis(self.analysis, self.properties)

    def test_property_key_mismatch_is_rejected(self) -> None:
        del self.payload["device"]["property_sha256"]["ro.product.model"]
        self._write()
        with self.assertRaises(AssemblyError):
            validate_preflight_analysis(self.analysis, self.properties)

    def test_binding_file_contains_hashes_only(self) -> None:
        binding = validate_preflight_analysis(self.analysis, self.properties)
        path = write_preflight_binding(self.root / "staging", binding)
        self.assertEqual(json.loads(path.read_text()), binding)
        self.assertNotIn("PJZ110", path.read_text())


if __name__ == "__main__":
    unittest.main()
