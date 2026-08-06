# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from featurelab.audit import audit_trees
from featurelab.generator import GenerationError, generate_payload


BASE_XML = """<?xml version="1.0" encoding="utf-8"?>
<config>
    <feature name="HdrGeneric"><supportApp>com.example.video</supportApp></feature>
    <rule name="ConfirmCredentialPassword" mode="fullscreen" />
    <rule name="PrivacyPasswordActivity" mode="fullscreen" />
    <rule name="FingerprintEnroll" mode="fullscreen" />
    <rule name="UnrelatedWindowPolicy" mode="freeform" />
</config>
"""

PERMISSIONS_XML = """<?xml version="1.0" encoding="utf-8"?>
<permissions>
    <privapp-permissions package="com.example.system">
        <permission name="android.permission.READ_PRIVILEGED_PHONE_STATE" />
        <permission name="android.permission.WRITE_SECURE_SETTINGS" />
    </privapp-permissions>
</permissions>
"""


class FeatureLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.generated = self.root / "generated"
        (self.baseline / "my_product/vendor/etc").mkdir(parents=True)
        (self.baseline / "system_ext/etc/permissions").mkdir(parents=True)
        (self.baseline / "my_product/vendor/etc/multimedia_display_feature_config.xml").write_text(
            BASE_XML, encoding="utf-8"
        )
        (self.baseline / "system_ext/etc/permissions/privapp-permissions-oplus-common.xml").write_text(
            PERMISSIONS_XML, encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_catalog(self, operations: list[dict]) -> Path:
        catalog = [
            {
                "id": "display.hdr.test",
                "title": "HDR test",
                "category": "display",
                "channel": "lab",
                "risk": "medium",
                "default_enabled": True,
                "evidence": {"state": "consumer_found"},
                "activation_stage": "post-mount",
                "operations": operations,
                "rollback": {"strategy": "baseline_restore", "verify": ["hash"]},
            }
        ]
        path = self.root / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def _copy_baseline_file(self, relative: str) -> None:
        destination = self.generated / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((self.baseline / relative).read_bytes())

    def test_generation_appends_hdr_and_preserves_protected_rules(self) -> None:
        catalog = self._write_catalog(
            [
                {
                    "type": "list_append",
                    "target": "/my_product/vendor/etc/multimedia_display_feature_config.xml",
                    "selector": "feature[name=HdrGeneric]/supportApp",
                    "value": "com.example.player",
                    "preserve_unrelated": True,
                }
            ]
        )
        report = self.root / "report.json"
        manifest = generate_payload(self.baseline, catalog, self.generated, report)
        text = (self.generated / "my_product/vendor/etc/multimedia_display_feature_config.xml").read_text()
        self.assertIn("com.example.video,com.example.player", text)
        self.assertIn("ConfirmCredentialPassword", text)
        self.assertEqual(manifest["audit_verdict"], "PASS")
        self.assertEqual(json.loads(report.read_text())["verdict"], "PASS")

    def test_audit_rejects_credential_rule_removal(self) -> None:
        self.generated.mkdir()
        target = self.generated / "my_product/vendor/etc/multimedia_display_feature_config.xml"
        target.parent.mkdir(parents=True)
        target.write_text(
            BASE_XML.replace('    <rule name="PrivacyPasswordActivity" mode="fullscreen" />\n', ""),
            encoding="utf-8",
        )
        self._copy_baseline_file("system_ext/etc/permissions/privapp-permissions-oplus-common.xml")
        report = audit_trees(self.baseline, self.generated)
        self.assertEqual(report.verdict, "FAIL")
        self.assertIn("PROTECTED_CREDENTIAL_SEMANTICS_CHANGED", {item.code for item in report.findings})

    def test_audit_rejects_permission_removal(self) -> None:
        self.generated.mkdir()
        self._copy_baseline_file("my_product/vendor/etc/multimedia_display_feature_config.xml")
        permissions = self.generated / "system_ext/etc/permissions/privapp-permissions-oplus-common.xml"
        permissions.parent.mkdir(parents=True)
        permissions.write_text(
            PERMISSIONS_XML.replace(
                '        <permission name="android.permission.WRITE_SECURE_SETTINGS" />\n', ""
            ),
            encoding="utf-8",
        )
        report = audit_trees(self.baseline, self.generated)
        self.assertEqual(report.verdict, "FAIL")
        self.assertIn("PRIVILEGED_PERMISSION_REMOVED", {item.code for item in report.findings})

    def test_audit_rejects_face_or_camera_semantic_addition(self) -> None:
        self.generated.mkdir()
        target = self.generated / "my_product/vendor/etc/multimedia_display_feature_config.xml"
        target.parent.mkdir(parents=True)
        target.write_text(
            BASE_XML.replace("</config>", '    <feature name="face_closeeye_detect" />\n</config>'),
            encoding="utf-8",
        )
        self._copy_baseline_file("system_ext/etc/permissions/privapp-permissions-oplus-common.xml")
        report = audit_trees(self.baseline, self.generated)
        self.assertEqual(report.verdict, "FAIL")
        self.assertIn("CAMERA_FACE_BIOMETRIC_BOUNDARY_CHANGED", {item.code for item in report.findings})

    def test_generator_rejects_camera_target(self) -> None:
        catalog = self._write_catalog(
            [
                {
                    "type": "xml_update",
                    "target": "/my_product/etc/camera/config.xml",
                    "selector": "feature[name=test]",
                    "value": {"attributes": {"enabled": "1"}},
                    "preserve_unrelated": True,
                }
            ]
        )
        with self.assertRaises(GenerationError):
            generate_payload(self.baseline, catalog, self.generated, self.root / "report.json")

    def test_property_audit_detects_duplicate_and_malformed_lines(self) -> None:
        baseline_prop = self.baseline / "system/etc/featurelab.prop"
        baseline_prop.parent.mkdir(parents=True)
        baseline_prop.write_text("persist.demo=0\n", encoding="utf-8")
        self.generated.mkdir()
        self._copy_baseline_file("my_product/vendor/etc/multimedia_display_feature_config.xml")
        self._copy_baseline_file("system_ext/etc/permissions/privapp-permissions-oplus-common.xml")
        generated_prop = self.generated / "system/etc/featurelab.prop"
        generated_prop.parent.mkdir(parents=True)
        generated_prop.write_text("persist.demo=0\npersist.demo=1\nbroken line\n", encoding="utf-8")
        report = audit_trees(self.baseline, self.generated)
        codes = {item.code for item in report.findings}
        self.assertIn("DUPLICATE_PROPERTY_KEYS", codes)
        self.assertIn("MALFORMED_PROPERTY_LINES", codes)

    def test_sparse_generated_tree_does_not_require_untouched_baseline_files(self) -> None:
        untouched = self.baseline / "vendor/etc/untouched.xml"
        untouched.parent.mkdir(parents=True)
        untouched.write_text('<config><item name="untouched" /></config>\n', encoding="utf-8")
        self.generated.mkdir()
        self._copy_baseline_file("my_product/vendor/etc/multimedia_display_feature_config.xml")
        report = audit_trees(self.baseline, self.generated)
        self.assertEqual(report.verdict, "PASS")

    def test_explicit_top_level_removal_is_allowed(self) -> None:
        base = self.baseline / "my_product/vendor/etc/multimedia_display_feature_config.xml"
        base.write_text(
            BASE_XML.replace("</config>", '    <feature name="ContradictoryMarker" />\n</config>'),
            encoding="utf-8",
        )
        catalog = self._write_catalog(
            [
                {
                    "type": "xml_remove_exact",
                    "target": "/my_product/vendor/etc/multimedia_display_feature_config.xml",
                    "selector": "feature[name=ContradictoryMarker]",
                    "preserve_unrelated": True,
                }
            ]
        )
        manifest = generate_payload(self.baseline, catalog, self.generated, self.root / "report.json")
        self.assertEqual(manifest["audit_verdict"], "PASS")
        self.assertNotIn(
            "ContradictoryMarker",
            (self.generated / "my_product/vendor/etc/multimedia_display_feature_config.xml").read_text(),
        )

    def test_surface_target_is_not_mistaken_for_face_target(self) -> None:
        target = self.baseline / "system/etc/surface_feature.xml"
        target.parent.mkdir(parents=True)
        target.write_text('<config><feature name="Display" enabled="0" /></config>\n', encoding="utf-8")
        catalog = self._write_catalog(
            [
                {
                    "type": "xml_update",
                    "target": "/system/etc/surface_feature.xml",
                    "selector": "feature[name=Display]",
                    "value": {"attributes": {"enabled": "1"}},
                    "preserve_unrelated": True,
                }
            ]
        )
        manifest = generate_payload(self.baseline, catalog, self.generated, self.root / "report.json")
        self.assertEqual(manifest["audit_verdict"], "PASS")

    def test_permission_addition_is_recorded_without_removing_original_grants(self) -> None:
        catalog = self._write_catalog(
            [
                {
                    "type": "permission_add",
                    "target": "/system_ext/etc/permissions/privapp-permissions-oplus-common.xml",
                    "selector": "privapp-permissions[package=com.example.system]",
                    "value": "android.permission.READ_LOGS",
                    "preserve_unrelated": True,
                }
            ]
        )
        generate_payload(self.baseline, catalog, self.generated, self.root / "report.json")
        report = json.loads((self.root / "report.json").read_text())
        additions = report["permission_additions"]
        self.assertEqual(
            additions["/system_ext/etc/permissions/privapp-permissions-oplus-common.xml"][
                "com.example.system"
            ],
            ["android.permission.READ_LOGS"],
        )

    def test_project_generation_manifest_is_allowed_without_vendor_baseline(self) -> None:
        self.generated.mkdir()
        self._copy_baseline_file("my_product/vendor/etc/multimedia_display_feature_config.xml")
        (self.generated / "featurelab-generation.json").write_text("{}\n", encoding="utf-8")
        report = audit_trees(self.baseline, self.generated)
        self.assertEqual(report.verdict, "PASS")


if __name__ == "__main__":
    unittest.main()
