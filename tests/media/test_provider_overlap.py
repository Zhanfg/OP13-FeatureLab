# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/media/audit-provider-overlap.py"


class ProviderOverlapTests(unittest.TestCase):
    def test_detects_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a = base / "a"
            b = base / "b"
            (a / "vendor/lib64").mkdir(parents=True)
            (b / "vendor/lib64").mkdir(parents=True)
            (a / "vendor/lib64/example.so.txt").write_text("a")
            (b / "vendor/lib64/example.so.txt").write_text("b")
            result = subprocess.run(
                ["python3", str(TOOL), f"a={a}", f"b={b}"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("CONFLICT\tvendor/lib64/example.so.txt\ta,b", result.stdout)

    def test_disjoint_payloads_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a = base / "a"
            b = base / "b"
            (a / "vendor/etc").mkdir(parents=True)
            (b / "odm/etc").mkdir(parents=True)
            (a / "vendor/etc/a.xml").write_text("a")
            (b / "odm/etc/b.xml").write_text("b")
            result = subprocess.run(
                ["python3", str(TOOL), f"a={a}", f"b={b}"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS\tconflicts\t0", result.stdout)


if __name__ == "__main__":
    unittest.main()
