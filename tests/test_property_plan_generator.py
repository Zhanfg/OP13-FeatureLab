# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from featurelab.generator import GenerationError, generate_payload
from featurelab.propertyplan import PropertyPlanError, build_property_plan, render_property_plan, scalar_to_property


class PropertyPlanGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _snapshot(self, properties: dict[str, dict[str, object]]) -> Path:
        path = self.root / "property-snapshot.json"
        path.write_text(json.dumps({"format": 1, "properties": properties}), encoding="utf-8")
        return path

    @staticmethod
    def _operation(
        key: str,
        value: object = "1",
        *,
        stage: str = "service",
        apply_mode: str = "direct",
        restart: str = "none",
    ) -> dict[str, object]:
        return {
            "type": "property_set",
            "key": key,
            "value": value,
            "stage": stage,
            "apply_mode": apply_mode,
            "restart": restart,
        }

    def _catalog(self, operation: dict[str, object]) -> Path:
        path = self.root / "catalog.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "id": "display.property.test",
                        "title": "Property test",
                        "category": "display",
                        "channel": "lab",
                        "risk": "medium",
                        "default_enabled": True,
                        "evidence": {"state": "consumer_found"},
                        "activation_stage": "service",
                        "operations": [operation],
                        "rollback": {"strategy": "property_restore", "verify": ["hash"]},
                    }
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_rows_are_sorted_by_stage_and_feature(self) -> None:
        rows, metadata = build_property_plan(
            [
                ("display.z", self._operation("persist.demo.z", stage="boot-completed")),
                ("display.a", self._operation("persist.demo.a", stage="early")),
                ("display.m", self._operation("persist.demo.m", stage="service")),
            ],
            self._snapshot(
                {
                    "persist.demo.z": {"state": "present", "value": "0"},
                    "persist.demo.a": {"state": "present", "value": "0"},
                    "persist.demo.m": {"state": "absent"},
                    "persist.demo.unused": {"state": "present", "value": "x"},
                }
            ),
        )
        self.assertEqual([row.stage for row in rows], ["early", "service", "boot-completed"])
        self.assertEqual([row.sequence for row in rows], [10, 20, 30])
        self.assertEqual(metadata["unused_snapshot_keys"], ["persist.demo.unused"])

    def test_present_baseline_is_hashed_not_serialized(self) -> None:
        rows, _ = build_property_plan(
            [("display.test", self._operation("persist.demo.secret"))],
            self._snapshot({"persist.demo.secret": {"state": "present", "value": "private-baseline-token"}}),
        )
        rendered = render_property_plan(rows).decode("utf-8")
        self.assertNotIn("private-baseline-token", rendered)
        self.assertIn("\tpresent\t", rendered)

    def test_absent_baseline_uses_zero_hash(self) -> None:
        rows, _ = build_property_plan(
            [("display.test", self._operation("persist.demo.absent"))],
            self._snapshot({"persist.demo.absent": {"state": "absent"}}),
        )
        fields = render_property_plan(rows).decode("utf-8").rstrip("\n").split("\t")
        self.assertEqual(fields[6], "absent")
        self.assertEqual(fields[7], "0" * 64)

    def test_empty_target_value_uses_dash_sentinel(self) -> None:
        rows, _ = build_property_plan(
            [("display.test", self._operation("persist.demo.empty", ""))],
            self._snapshot({"persist.demo.empty": {"state": "present", "value": "old"}}),
        )
        fields = render_property_plan(rows).decode("utf-8").rstrip("\n").split("\t")
        self.assertEqual(fields[4], "-")

    def test_boolean_values_are_normalized(self) -> None:
        self.assertEqual(scalar_to_property(True), "true")
        self.assertEqual(scalar_to_property(False), "false")

    def test_property_value_byte_limit_is_enforced(self) -> None:
        self.assertEqual(scalar_to_property("a" * 91), "a" * 91)
        with self.assertRaises(PropertyPlanError):
            scalar_to_property("a" * 92)

    def test_non_finite_numbers_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(PropertyPlanError):
                scalar_to_property(value)

    def test_control_characters_are_rejected(self) -> None:
        for value in ("line\nbreak", "line\rbreak", "nul\x00byte"):
            with self.subTest(value=value), self.assertRaises(PropertyPlanError):
                scalar_to_property(value)

    def test_multi_segment_face_detection_key_is_rejected(self) -> None:
        with self.assertRaises(PropertyPlanError):
            build_property_plan(
                [("security.bad", self._operation("persist.vendor.face_closeeye_detect"))],
                self._snapshot({"persist.vendor.face_closeeye_detect": {"state": "present", "value": "0"}}),
            )

    def test_surface_feature_detector_is_not_false_positive(self) -> None:
        rows, _ = build_property_plan(
            [("display.surface", self._operation("persist.vendor.surface_feature_detector"))],
            self._snapshot({"persist.vendor.surface_feature_detector": {"state": "present", "value": "0"}}),
        )
        self.assertEqual(rows[0].key, "persist.vendor.surface_feature_detector")

    def test_duplicate_property_ownership_is_rejected(self) -> None:
        snapshot = self._snapshot({"persist.demo.shared": {"state": "present", "value": "0"}})
        with self.assertRaises(PropertyPlanError):
            build_property_plan(
                [
                    ("display.one", self._operation("persist.demo.shared", "1")),
                    ("display.two", self._operation("persist.demo.shared", "2", stage="boot-completed")),
                ],
                snapshot,
            )

    def test_missing_snapshot_key_is_rejected(self) -> None:
        with self.assertRaises(PropertyPlanError):
            build_property_plan(
                [("display.test", self._operation("persist.demo.missing"))],
                self._snapshot({}),
            )

    def test_early_trigger_and_trigger_without_restart_are_rejected(self) -> None:
        snapshot = self._snapshot({"persist.demo.mode": {"state": "present", "value": "0"}})
        with self.assertRaises(PropertyPlanError):
            build_property_plan(
                [
                    (
                        "display.test",
                        self._operation(
                            "persist.demo.mode",
                            stage="early",
                            apply_mode="trigger",
                            restart="reboot",
                        ),
                    )
                ],
                snapshot,
            )
        with self.assertRaises(PropertyPlanError):
            build_property_plan(
                [
                    (
                        "display.test",
                        self._operation(
                            "persist.demo.mode",
                            stage="service",
                            apply_mode="trigger",
                            restart="none",
                        ),
                    )
                ],
                snapshot,
            )

    def test_generator_requires_snapshot_for_selected_property_operations(self) -> None:
        with self.assertRaises(GenerationError):
            generate_payload(
                self.baseline,
                self._catalog(self._operation("persist.demo.required")),
                self.root / "output",
                self.root / "report.json",
            )

    def test_generator_emits_property_plan_without_prop_payload(self) -> None:
        snapshot = self._snapshot({"persist.demo.hdr": {"state": "present", "value": "private-old-value"}})
        output = self.root / "output"
        manifest = generate_payload(
            self.baseline,
            self._catalog(self._operation("persist.demo.hdr", "1")),
            output,
            self.root / "report.json",
            property_snapshot_path=snapshot,
        )
        plan = (output / "property-plan.tsv").read_text(encoding="utf-8")
        self.assertIn("persist.demo.hdr", plan)
        self.assertIn("\tMQ==\t", plan)
        self.assertNotIn("private-old-value", plan)
        self.assertFalse(list(output.rglob("*.prop")))
        self.assertEqual(manifest["property_plan"]["row_count"], 1)
        self.assertEqual(manifest["audit_verdict"], "PASS")

    def test_generator_rejects_legacy_prop_file_shape_without_replacing_output(self) -> None:
        output = self.root / "output"
        output.mkdir()
        marker = output / "previous-valid-output.txt"
        marker.write_text("keep", encoding="utf-8")
        operation = {
            "type": "property_set",
            "target": "/system/etc/legacy.prop",
            "selector": "persist.demo.legacy",
            "value": "1",
        }
        with self.assertRaises(GenerationError):
            generate_payload(
                self.baseline,
                self._catalog(operation),
                output,
                self.root / "report.json",
                property_snapshot_path=self._snapshot(
                    {"persist.demo.legacy": {"state": "present", "value": "0"}}
                ),
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
