# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
STATUS = REPO / "scripts/webui/status.sh"


class WebUIStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mod = self.root / "module"
        self.bin = self.root / "bin"
        self.proc = self.root / "proc"
        (self.mod / "generated").mkdir(parents=True)
        (self.mod / "state/runtime").mkdir(parents=True)
        (self.mod / "state/properties").mkdir(parents=True)
        (self.bin).mkdir()
        (self.proc / "sys/kernel/random").mkdir(parents=True)
        (self.proc / "self/ns").mkdir(parents=True)
        (self.proc / "1/ns").mkdir(parents=True)
        (self.proc / "sys/kernel/random/boot_id").write_text("boot-private-value\n")
        os.symlink("mnt:[44]", self.proc / "self/ns/mnt")
        os.symlink("mnt:[44]", self.proc / "1/ns/mnt")
        (self.mod / "module.prop").write_text(
            "id=op13.featurelab.validation\nname=FeatureLab\nversion=0.1.0-validation\nversionCode=1\n"
        )
        (self.mod / "generated/mount-plan.tsv").write_text("10\tf\tpayload/x\t/system/x\t" + "1"*64 + "\t" + "2"*64 + "\tstatic-ro\n")
        (self.mod / "generated/property-plan.tsv").write_text("")
        (self.mod / "generated/validation-only.flag").write_text("NOT_FLASH_READY\n")
        self._write_fake_commands()
        self._write_checksums()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_exe(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def _write_fake_commands(self) -> None:
        self._write_exe("getprop", r'''
case "$1" in
 ro.product.device) printf 'PJZ110' ;;
 ro.product.model) printf 'OnePlus 13' ;;
 ro.build.version.sdk) printf '36' ;;
 ro.build.version.oplusrom) printf 'V16.1.0' ;;
 ro.build.fingerprint) printf 'private/fingerprint/value' ;;
 sys.boot_completed) printf '1' ;;
esac
''')
        self._write_exe("getenforce", "printf 'Enforcing\n'\n")
        self._write_exe("cmd", "printf 'android:color/system_accent1_500 -> #ff336699\n'\n")
        for name in ("mount", "umount", "setprop", "resetprop", "reboot", "stop", "start"):
            self._write_exe(name, f"printf '{name}\\n' >> {self.root / 'mutation.log'}\nexit 99\n")

    def _write_checksums(self) -> None:
        rows = []
        for relative in ("module.prop", "generated/mount-plan.tsv", "generated/property-plan.tsv", "generated/validation-only.flag"):
            digest = hashlib.sha256((self.mod / relative).read_bytes()).hexdigest()
            rows.append(f"{digest}  {relative}")
        (self.mod / "generated/package-files.sha256").write_text("\n".join(rows) + "\n")

    def _run(self) -> dict:
        env = os.environ.copy()
        env.update({
            "FEATURELAB_MODDIR": str(self.mod),
            "FEATURELAB_PROC_ROOT": str(self.proc),
            "FEATURELAB_GETPROP_BIN": str(self.bin / "getprop"),
            "FEATURELAB_GETENFORCE_BIN": str(self.bin / "getenforce"),
            "FEATURELAB_CMD_BIN": str(self.bin / "cmd"),
            "PATH": f"{self.bin}:{env['PATH']}",
        })
        result = subprocess.run(["sh", str(STATUS), "status"], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("private/fingerprint/value", result.stdout)
        self.assertNotIn("boot-private-value", result.stdout)
        return json.loads(result.stdout)

    def test_idle_truthful_status(self) -> None:
        value = self._run()
        self.assertTrue(value["read_only"])
        self.assertFalse(value["capabilities"]["mutation_enabled"])
        self.assertEqual(value["runtime"]["status"], "idle")
        self.assertEqual(value["properties"]["status"], "idle")
        self.assertEqual(value["integrity"]["status"], "pass")
        self.assertEqual(value["theme"], {"source": "system", "seed": "#336699"})
        self.assertEqual(value["runtime"]["namespace"], "same")
        self.assertFalse((self.root / "mutation.log").exists())

    def test_committed_counts(self) -> None:
        runtime_journal = self.mod / "state/runtime/transaction-boot-1.tsv"
        runtime_journal.write_text("MOUNTED\ttx\t10\tf\ts\t/system/x\ta\tb\t1\t2\t1\t0:1\t/\ts\text4\n")
        (self.mod / "state/runtime/active-journal").write_text(str(runtime_journal))
        (self.mod / "state/runtime/commit").write_text("tx 1 " + "a"*64 + " boot-private-value\n")
        stage = self.mod / "state/properties/service"
        stage.mkdir(parents=True)
        prop_journal = stage / "transaction-boot-1.tsv"
        prop_journal.write_text("OWNED\ttx\t10\tf\tservice\tpersist.x\tabsent\t\t" + "0"*64 + "\t" + "1"*64 + "\tdirect\tnone\n")
        (stage / "active-journal").write_text(str(prop_journal))
        (stage / "commit").write_text("tx " + "a"*64 + " boot-private-value\n")
        value = self._run()
        self.assertEqual(value["runtime"]["status"], "committed")
        self.assertEqual(value["runtime"]["active_mounts"], 1)
        self.assertEqual(value["properties"]["status"], "committed")
        self.assertEqual(value["properties"]["active_properties"], 1)

    def test_unsupported_action_is_rejected(self) -> None:
        env = os.environ.copy()
        env["FEATURELAB_MODDIR"] = str(self.mod)
        result = subprocess.run(["sh", str(STATUS), "apply"], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"], "unsupported_action")

    def test_incomplete_and_integrity_failure(self) -> None:
        (self.mod / "state/runtime/commit").write_text("orphan\n")
        (self.mod / "module.prop").write_text((self.mod / "module.prop").read_text() + "description=changed\n")
        value = self._run()
        self.assertEqual(value["runtime"]["status"], "incomplete")
        self.assertEqual(value["integrity"]["status"], "fail")
        self.assertIn("runtime.incomplete", value["errors"])
        self.assertIn("integrity.failed", value["errors"])


class WebUIStaticTests(unittest.TestCase):
    def test_no_simulated_success_path(self) -> None:
        text = (REPO / "src/webui/app.js").read_text()
        lowered = text.lower()
        for forbidden in ("mockrun", "mock success", "fake device", "demo success"):
            self.assertNotIn(forbidden, lowered)
        self.assertNotIn('import("kernelsu")', text)
        self.assertIn("globalThis.ksu", text)
        self.assertIn("bridge.moduleInfo", text)
        self.assertIn("__FEATURELAB_RC__=", text)
        self.assertIn("result.errno", text)
        self.assertIn("mutation_enabled", text)
        self.assertNotIn("mountctl.sh apply", text)
        self.assertNotIn("propctl.sh apply", text)

    def test_webui_entry_and_dynamic_color(self) -> None:
        html = (REPO / "src/webui/index.html").read_text()
        css = (REPO / "src/webui/style.css").read_text()
        self.assertIn('id="fatal"', html)
        self.assertIn('id="runtime-status"', html)
        self.assertIn('type="module"', html)
        self.assertIn("--primary", css)
        self.assertIn("prefers-reduced-motion", css)

    @unittest.skipUnless(shutil.which("node"), "node is unavailable")
    def test_javascript_syntax(self) -> None:
        result = subprocess.run(["node", "--check", str(REPO / "src/webui/app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
