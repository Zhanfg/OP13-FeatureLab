# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from featurelab.assembler import _augment_customize_metadata
from featurelab.assembly_policy import AssemblyError
from featurelab.assembly_webui import copy_webui_assets


class WebUIAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.staging = self.root / "staging"
        (self.source / "src/webui").mkdir(parents=True)
        (self.source / "scripts/webui").mkdir(parents=True)
        self.staging.mkdir()
        for name, body in {
            "index.html": "<!doctype html><title>x</title>\n",
            "style.css": ":root{}\n",
            "app.js": "import {MODULE_ID} from './runtime-config.js';\n",
            "runtime-config.js": "placeholder\n",
        }.items():
            (self.source / "src/webui" / name).write_text(body)
        bridge = self.source / "scripts/webui/status.sh"
        bridge.write_text("#!/system/bin/sh\nexit 0\n")
        os.chmod(bridge, 0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_copies_webui_and_generates_validated_module_id(self) -> None:
        result = copy_webui_assets(self.source, self.staging, "custom.module-id")
        self.assertTrue(result["included"])
        self.assertEqual(result["file_count"], 5)
        config = (self.staging / "webroot/runtime-config.js").read_text()
        self.assertIn('MODULE_ID = "custom.module-id"', config)
        self.assertTrue((self.staging / "webroot/index.html").is_file())
        self.assertEqual((self.staging / "scripts/webui/status.sh").stat().st_mode & 0o777, 0o755)

    def test_absent_webui_is_backward_compatible(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(
            copy_webui_assets(empty, self.staging, "x.y"),
            {"included": False, "file_count": 0},
        )

    def test_partial_webui_is_rejected(self) -> None:
        (self.source / "scripts/webui/status.sh").unlink()
        with self.assertRaises(AssemblyError):
            copy_webui_assets(self.source, self.staging, "x.y")

    def test_webui_symlink_is_rejected(self) -> None:
        link = self.source / "src/webui/leak.js"
        try:
            link.symlink_to(self.source / "src/webui/app.js")
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(AssemblyError):
            copy_webui_assets(self.source, self.staging, "x.y")

    def test_customize_does_not_recursively_touch_webroot(self) -> None:
        customize = self.staging / "customize.sh"
        customize.write_text(
            '#!/system/bin/sh\nset_perm_recursive "$MODPATH" 0 0 0755 0644\n'
        )
        _augment_customize_metadata(self.staging)
        text = customize.read_text()
        self.assertNotIn('set_perm_recursive "$MODPATH" 0 0 0755 0644', text)
        self.assertIn('set_perm_recursive "$MODPATH/generated"', text)
        self.assertIn('set_perm_recursive "$MODPATH/scripts"', text)
        self.assertIn('Do not recursively change webroot', text)
        self.assertNotIn('set_perm_recursive "$MODPATH/webroot"', text)

    def test_assembler_calls_webui_packager(self) -> None:
        text = (
            Path(__file__).resolve().parents[1] / "src/featurelab/assembler.py"
        ).read_text()
        self.assertIn(
            "copy_webui_assets(source, staging, metadata.module_id)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
