# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from featurelab.snapshot import (
    SnapshotError,
    capture_property_snapshot,
    parse_getprop_dump,
    selected_property_keys,
)


class AllowlistedPropertySnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _catalog(self, features: list[dict]) -> Path:
        path = self.root / "catalog.json"
        path.write_text(json.dumps(features), encoding="utf-8")
        return path

    def _dump(self, text: str) -> Path:
        path = self.root / "getprop.private.txt"
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def _feature(feature_id: str, key: str | None, *, default_enabled: bool = True) -> dict:
        operations = []
        if key is not None:
            operations.append(
                {
                    "type": "property_set",
                    "key": key,
                    "value": "1",
                    "stage": "service",
                    "apply_mode": "direct",
                    "restart": "none",
                }
            )
        return {
            "id": feature_id,
            "default_enabled": default_enabled,
            "operations": operations,
        }

    def test_snapshot_keeps_only_selected_keys(self) -> None:
        catalog = self._catalog(
            [
                self._feature("display.one", "persist.demo.one"),
                self._feature("display.two", "persist.demo.two", default_enabled=False),
            ]
        )
        output = self.root / "snapshot.json"
        metadata = capture_property_snapshot(
            catalog,
            self._dump("[persist.demo.one]: [0]\n[secret.unrelated]: [private-token]\n"),
            output,
            selected_features={"display.one"},
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["properties"], {"persist.demo.one": {"state": "present", "value": "0"}})
        self.assertNotIn("private-token", output.read_text(encoding="utf-8"))
        self.assertEqual(metadata["present_count"], 1)

    def test_missing_selected_key_is_explicitly_absent(self) -> None:
        catalog = self._catalog([self._feature("display.one", "persist.demo.one")])
        output = self.root / "snapshot.json"
        metadata = capture_property_snapshot(catalog, self._dump("[persist.other]: [1]\n"), output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["properties"]["persist.demo.one"], {"state": "absent"})
        self.assertEqual(metadata["absent_count"], 1)

    def test_empty_property_value_remains_present(self) -> None:
        catalog = self._catalog([self._feature("display.one", "persist.demo.one")])
        output = self.root / "snapshot.json"
        capture_property_snapshot(catalog, self._dump("[persist.demo.one]: []\n"), output)
        self.assertEqual(json.loads(output.read_text())["properties"]["persist.demo.one"]["value"], "")

    def test_malformed_dump_does_not_replace_previous_snapshot(self) -> None:
        catalog = self._catalog([self._feature("display.one", "persist.demo.one")])
        output = self.root / "snapshot.json"
        output.write_text("previous-valid", encoding="utf-8")
        with self.assertRaises(SnapshotError):
            capture_property_snapshot(catalog, self._dump("malformed getprop output\n"), output)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous-valid")

    def test_duplicate_getprop_key_is_rejected(self) -> None:
        with self.assertRaises(SnapshotError):
            parse_getprop_dump(self._dump("[persist.demo]: [1]\n[persist.demo]: [2]\n"))

    def test_unknown_selected_feature_is_rejected(self) -> None:
        catalog = self._catalog([self._feature("display.one", "persist.demo.one")])
        with self.assertRaises(SnapshotError):
            selected_property_keys(catalog, {"display.missing"})

    def test_duplicate_feature_ownership_is_rejected(self) -> None:
        catalog = self._catalog(
            [
                self._feature("display.one", "persist.demo.shared"),
                self._feature("display.two", "persist.demo.shared"),
            ]
        )
        with self.assertRaises(SnapshotError):
            selected_property_keys(catalog, None)

    def test_protected_face_detection_key_is_rejected(self) -> None:
        catalog = self._catalog(
            [self._feature("security.bad", "persist.vendor.face_closeeye_detect")]
        )
        with self.assertRaises(SnapshotError):
            selected_property_keys(catalog, None)

    def test_default_selection_excludes_disabled_features(self) -> None:
        catalog = self._catalog(
            [
                self._feature("display.one", "persist.demo.one"),
                self._feature("display.two", "persist.demo.two", default_enabled=False),
            ]
        )
        self.assertEqual(selected_property_keys(catalog, None), ["persist.demo.one"])

    def test_surface_detector_is_not_mistaken_for_face_key(self) -> None:
        catalog = self._catalog(
            [self._feature("display.surface", "persist.vendor.surface_feature_detector")]
        )
        self.assertEqual(
            selected_property_keys(catalog, None),
            ["persist.vendor.surface_feature_detector"],
        )


if __name__ == "__main__":
    unittest.main()
