# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/media/audit-inert-provider-root.py"

class InertProviderRootTests(unittest.TestCase):
    def run_tool(self, repo: Path, root: str):
        return subprocess.run(["python3", str(TOOL), "--repo", str(repo), root], text=True, capture_output=True)

    def test_inert_reference_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / "provider"
            root.mkdir()
            (root / "README.md").write_text("reference only\n")
            (root / "status.sh").write_text("#!/system/bin/sh\nservice list\nmount\n")
            result = self.run_tool(repo, "provider")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_mutation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            root = repo / "provider"
            root.mkdir()
            (root / "service.sh").write_text("#!/system/bin/sh\n/vendor/bin/hw/example-service &\n")
            result = self.run_tool(repo, "provider")
            self.assertEqual(result.returncode, 1)
            self.assertIn("direct-vendor-binary-launch", result.stderr)

    def test_active_vintf_overlay_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            path = repo / "provider/vendor/etc/vintf"
            path.mkdir(parents=True)
            (path / "manifest.xml").write_text("<manifest/>\n")
            result = self.run_tool(repo, "provider")
            self.assertEqual(result.returncode, 1)
            self.assertIn("active-vintf-overlay", result.stderr)

if __name__ == "__main__":
    unittest.main()
