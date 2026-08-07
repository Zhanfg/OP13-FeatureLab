# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from featurelab.compatibility import CompatibilityBuildError, build_compatibility_profile
from featurelab.util import sha256_file


class CompatibilityProfileBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.generated = self.root / "generated"
        self.generated.mkdir()
        self.manifest = self.generated / "featurelab-generation.json"
        self.dump = self.root / "getprop.private.txt"
        self.output = self.root / "compatibility-profile.private.json"
        self._write_manifest()
        self._write_dump()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_manifest(self, mutate=None) -> None:
        value = {
            "selected_features": ["display.hdr"],
            "targets": {
                "/my_product/vendor/etc/display.xml": {
                    "baseline_sha256": "1" * 64,
                    "generated_sha256": "2" * 64,
                    "source_metadata": {"mode": "0o644", "uid": 0, "gid": 0, "selinux": None},
                }
            },
            "operations": [
                {
                    "feature_id": "display.hdr",
                    "operation": "xml_update",
                    "target": "/my_product/vendor/etc/display.xml",
                }
            ],
            "property_plan": None,
            "audit_verdict": "PASS",
        }
        if mutate:
            mutate(value)
        self.manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _properties(self) -> dict[str, str]:
        return {
            "ro.product.device": "PJZ110",
            "ro.product.model": "PJZ110",
            "ro.build.version.sdk": "36",
            "ro.build.fingerprint": "synthetic/PJZ110/test:16/build:user/release-keys",
            "ro.build.version.incremental": "PJZ110_16.0.9.402",
            "ro.build.version.oplusrom": "V16.1.0",
            "ro.product.manufacturer": "OnePlus",
            "ro.product.name": "PJZ110",
            "persist.unrelated.secret": "must-not-be-copied",
        }

    def _write_dump(self, mutate=None) -> None:
        props = self._properties()
        if mutate:
            mutate(props)
        text = "".join(f"[{key}]: [{value}]\n" for key, value in sorted(props.items()))
        self.dump.write_text(text, encoding="utf-8")

    def _build(self, **kwargs):
        return build_compatibility_profile(
            self.manifest,
            self.dump,
            self.output,
            minimum_ksu_version_code=12000,
            minimum_ksu_kernel_version_code=12000,
            **kwargs,
        )

    def test_happy_profile_is_bound_to_manifest_and_baselines(self) -> None:
        result = self._build()
        profile = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(profile["generation_manifest_sha256"], sha256_file(self.manifest))
        self.assertEqual(
            profile["baselines"],
            {"/my_product/vendor/etc/display.xml": "1" * 64},
        )
        self.assertEqual(result["target_count"], 1)

    def test_unrelated_property_is_not_copied_or_reported(self) -> None:
        result = self._build()
        profile_text = self.output.read_text(encoding="utf-8")
        self.assertNotIn("persist.unrelated.secret", profile_text)
        self.assertNotIn("must-not-be-copied", profile_text)
        self.assertNotIn("must-not-be-copied", json.dumps(result))

    def test_optional_properties_are_included_only_when_present(self) -> None:
        self._write_dump(lambda props: props.pop("ro.product.name"))
        self._build()
        profile = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertNotIn("ro.product.name", profile["properties"])
        self.assertEqual(profile["properties"]["ro.product.manufacturer"], "OnePlus")

    def test_long_fingerprint_and_unrelated_values_do_not_hit_property_plan_limit(self) -> None:
        self._write_dump(
            lambda props: (
                props.__setitem__("ro.build.fingerprint", "f" * 180),
                props.__setitem__("persist.unrelated.secret", "x" * 500),
            )
        )
        self._build()
        profile = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(profile["properties"]["ro.build.fingerprint"], "f" * 180)
        self.assertNotIn("persist.unrelated.secret", profile["properties"])

    def test_missing_required_property_is_rejected(self) -> None:
        self._write_dump(lambda props: props.pop("ro.build.fingerprint"))
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_wrong_device_is_rejected(self) -> None:
        self._write_dump(lambda props: props.__setitem__("ro.product.device", "OTHER"))
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_wrong_sdk_is_rejected(self) -> None:
        self._write_dump(lambda props: props.__setitem__("ro.build.version.sdk", "35"))
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_wrong_oplus_rom_generation_is_rejected(self) -> None:
        self._write_dump(lambda props: props.__setitem__("ro.build.version.oplusrom", "V16.0.0"))
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_non_pass_generation_is_rejected(self) -> None:
        self._write_manifest(lambda value: value.__setitem__("audit_verdict", "FAIL"))
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_invalid_baseline_hash_is_rejected(self) -> None:
        def mutate(value):
            value["targets"]["/my_product/vendor/etc/display.xml"]["baseline_sha256"] = "bad"
        self._write_manifest(mutate)
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_target_control_character_is_rejected(self) -> None:
        original = "/my_product/vendor/etc/display.xml"
        bad = original + "\nsecond"
        def mutate(value):
            metadata = value["targets"].pop(original)
            value["targets"][bad] = metadata
        self._write_manifest(mutate)
        with self.assertRaises(CompatibilityBuildError):
            self._build()

    def test_negative_ksu_minimum_is_rejected(self) -> None:
        with self.assertRaises(CompatibilityBuildError):
            build_compatibility_profile(
                self.manifest,
                self.dump,
                self.output,
                minimum_ksu_version_code=-1,
                minimum_ksu_kernel_version_code=0,
            )

    def test_malformed_getprop_preserves_previous_output(self) -> None:
        self.output.write_text("previous-valid", encoding="utf-8")
        self.dump.write_text("malformed\n", encoding="utf-8")
        with self.assertRaises(CompatibilityBuildError):
            self._build()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "previous-valid")

    def test_output_inside_generated_tree_is_rejected(self) -> None:
        with self.assertRaises(CompatibilityBuildError):
            build_compatibility_profile(
                self.manifest,
                self.dump,
                self.generated / "compatibility-profile.private.json",
                minimum_ksu_version_code=0,
                minimum_ksu_kernel_version_code=0,
            )


if __name__ == "__main__":
    unittest.main()
