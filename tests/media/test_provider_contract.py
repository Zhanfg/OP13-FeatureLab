# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/media/validate-provider-contract.py"
EXAMPLE = ROOT / "config/media-provider-contract.example.json"


class ProviderContractTests(unittest.TestCase):
    def base(self) -> dict:
        return json.loads(EXAMPLE.read_text())

    def run_tool(self, value: dict):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            path.write_text(json.dumps(value))
            return subprocess.run(
                ["python3", str(TOOL), "--contract", str(path), "--max-age-days", "-1"],
                text=True,
                capture_output=True,
            )

    def test_example_passes(self):
        result = self.run_tool(self.base())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"valid": true', result.stdout)

    def test_architecture_only_is_not_resolved(self):
        value = self.base()
        edge = value["edges"][0]
        edge["soname"] = "unknown"
        edge["symbol_abi"] = "unknown"
        edge["namespace"] = "unknown"
        result = self.run_tool(value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("soname=match", result.stderr)

    def test_dlopen_candidate_needs_runtime_observation(self):
        value = self.base()
        edge = copy.deepcopy(value["edges"][0])
        edge["edge_id"] = "elf:dlopen"
        edge["edge_type"] = "elf-dlopen-candidate"
        edge["resolution"] = "static-resolved"
        value["edges"].append(edge)
        value["closures"]["static"].append(edge["edge_id"])
        result = self.run_tool(value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dlopen candidates cannot be promoted", result.stderr)

    def test_platform_compatible_requires_namespace_visibility(self):
        value = self.base()
        row = value["target_platform_contracts"][0]
        row["namespace"] = "not-visible"
        result = self.run_tool(value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("namespace=visible", result.stderr)

    def test_observed_closure_requires_runtime_resolution(self):
        value = self.base()
        value["closures"]["observed_runtime"] = ["xml:codec-include"]
        value["closures"]["declarative"] = []
        result = self.run_tool(value)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("observed-runtime resolution", result.stderr)


if __name__ == "__main__":
    unittest.main()
