# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/media/validate-decoder-evidence.py"

class DecoderEvidenceTests(unittest.TestCase):
    def base_report(self) -> dict:
        return {
            "schema": 1,
            "generated_at_utc": "2026-09-28T17:30:00Z",
            "device": {"product": "SYNTHETIC", "sdk": 36, "build_fingerprint_sha256": "1" * 64},
            "candidate_manifest_sha256": "2" * 64,
            "decoders": [{
                "mime": "audio/example",
                "component": "c2.example.decoder",
                "decoder_discovered": True,
                "create_ok": True,
                "output_mime": "audio/raw",
                "pcm_bytes": 4096,
                "pcm_frames": 1024,
                "input_sha256": "3" * 64,
                "pcm_sha256": "4" * 64,
            }],
        }

    def run_tool(self, report: dict, *extra: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(report))
            return subprocess.run(
                ["python3", str(TOOL), "--report", str(path), "--max-age-days", "-1", *extra],
                text=True, capture_output=True,
            )

    def test_valid_report(self):
        result = self.run_tool(self.base_report(), "--require-mime", "audio/example")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"valid": true', result.stdout)

    def test_component_creation_must_succeed(self):
        report = self.base_report()
        report["decoders"][0]["create_ok"] = False
        result = self.run_tool(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("create_ok must be true", result.stderr)

    def test_pcm_must_be_positive(self):
        report = self.base_report()
        report["decoders"][0]["pcm_bytes"] = 0
        result = self.run_tool(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pcm_bytes must be a positive integer", result.stderr)

if __name__ == "__main__":
    unittest.main()
