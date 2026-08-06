# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from featurelab.audit import audit_trees
from featurelab.generator import generate_payload


class EdgeCaseTests(unittest.TestCase):
    def test_xml_comments_are_preserved_and_do_not_crash_semantic_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline"
            output = root / "output"
            target = baseline / "my_product/vendor/etc/display.xml"
            target.parent.mkdir(parents=True)
            target.write_text(
                """<config>
    <!-- display policy -->
    <feature name="HdrGeneric"><supportApp>com.example.video</supportApp></feature>
    <rule name="ConfirmCredentialPassword" />
</config>
""",
                encoding="utf-8",
            )
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    [
                        {
                            "id": "display.comment.test",
                            "title": "Comment test",
                            "category": "display",
                            "channel": "lab",
                            "risk": "medium",
                            "default_enabled": True,
                            "evidence": {"state": "consumer_found"},
                            "activation_stage": "post-mount",
                            "operations": [
                                {
                                    "type": "list_append",
                                    "target": "/my_product/vendor/etc/display.xml",
                                    "selector": "feature[name=HdrGeneric]/supportApp",
                                    "value": "com.example.player",
                                    "preserve_unrelated": True,
                                }
                            ],
                            "rollback": {"strategy": "baseline_restore", "verify": ["hash"]},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            manifest = generate_payload(baseline, catalog, output, root / "report.json")
            generated = (output / "my_product/vendor/etc/display.xml").read_text()
            self.assertEqual(manifest["audit_verdict"], "PASS")
            self.assertIn("display policy", generated)

    def test_protected_paths_in_baseline_only_do_not_fail_sparse_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline"
            generated = root / "generated"
            protected = baseline / "data/system/locksettings.db"
            protected.parent.mkdir(parents=True)
            protected.write_text("baseline-only", encoding="utf-8")
            source = baseline / "my_product/vendor/etc/display.xml"
            source.parent.mkdir(parents=True)
            source.write_text('<config><feature name="Display" /></config>\n', encoding="utf-8")
            destination = generated / "my_product/vendor/etc/display.xml"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(source.read_bytes())
            report = audit_trees(baseline, generated)
            self.assertEqual(report.verdict, "PASS")


if __name__ == "__main__":
    unittest.main()
