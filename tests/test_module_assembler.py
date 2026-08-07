# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from featurelab.assembler import assemble_validation_module
from featurelab.assembly_policy import AssemblyError, ModuleMetadata
from featurelab.util import sha256_file


class ModuleAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.generated = self.root / "generated-input"
        self.output = self.root / "assembled"
        self.profile = self.root / "compatibility-profile.private.json"
        self._make_source()
        self._make_generated()
        self._write_profile()
        self.metadata = ModuleMetadata(
            module_id="op13.featurelab.validation",
            name="OP13 FeatureLab Validation",
            version="0.1.0-validation",
            version_code=1,
            author="Axymorrsen",
            description="Local PJZ110 validation package",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _sha(data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def _make_source(self) -> None:
        (self.source / "module-template").mkdir(parents=True)
        for name in (
            "post-fs-data.sh",
            "post-mount.sh",
            "late-load.sh",
            "service.sh",
            "boot-completed.sh",
            "uninstall.sh",
        ):
            path = self.source / "module-template" / name
            path.write_text("#!/system/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(path, 0o755)
        for subtree in ("scripts/runtime", "scripts/properties"):
            directory = self.source / subtree
            directory.mkdir(parents=True)
            script = directory / "entry.sh"
            script.write_text("#!/system/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(script, 0o755)
        (self.source / "LICENSE").write_text("synthetic GPL text\n", encoding="utf-8")
        (self.source / "THIRD_PARTY_NOTICES.md").write_text("synthetic notices\n", encoding="utf-8")

    def _manifest(self, *, with_property: bool = False) -> dict:
        target = "/my_product/vendor/etc/display.xml"
        xml = (self.generated / target.lstrip("/")).read_bytes()
        operations = [
            {
                "feature_id": "display.hdr",
                "target": target,
                "operation": "xml_update",
                "matched": 1,
                "changed": 1,
            }
        ]
        property_plan = None
        if with_property:
            operations.append(
                {
                    "feature_id": "display.prop",
                    "target": "property-plan.tsv",
                    "operation": "property_set",
                    "key": "persist.vendor.display.demo",
                    "stage": "service",
                    "apply_mode": "direct",
                    "restart": "none",
                }
            )
            plan = (self.generated / "property-plan.tsv").read_bytes()
            property_plan = {
                "row_count": 1,
                "plan_sha256": self._sha(plan),
                "snapshot_sha256": "1" * 64,
                "selected_keys": ["persist.vendor.display.demo"],
                "unused_snapshot_keys": [],
            }
        return {
            "catalog_sha256": "2" * 64,
            "selected_features": ["display.hdr"] + (["display.prop"] if with_property else []),
            "targets": {
                target: {
                    "baseline_sha256": "3" * 64,
                    "generated_sha256": self._sha(xml),
                    "source_metadata": {
                        "mode": "0o644",
                        "uid": 0,
                        "gid": 0,
                        "size": len(xml),
                        "selinux": "u:object_r:vendor_configs_file:s0",
                    },
                }
            },
            "property_plan": property_plan,
            "operations": operations,
            "audit_verdict": "PASS",
        }

    def _make_generated(self, *, with_property: bool = False) -> None:
        target = self.generated / "my_product/vendor/etc/display.xml"
        target.parent.mkdir(parents=True)
        target.write_text("<features><feature name=\"hdr\" value=\"true\" /></features>\n", encoding="utf-8")
        if with_property:
            (self.generated / "property-plan.tsv").write_text(
                "10\tdisplay.prop\tservice\tpersist.vendor.display.demo\tMQ==\t"
                + self._sha("1")
                + "\tpresent\t"
                + self._sha("0")
                + "\tdirect\tnone\n",
                encoding="utf-8",
            )
        manifest = self._manifest(with_property=with_property)
        (self.generated / "featurelab-generation.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _rewrite_manifest(self, mutate) -> None:
        path = self.generated / "featurelab-generation.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        mutate(manifest)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._write_profile()

    def _profile_value(self) -> dict:
        manifest_sha = sha256_file(self.generated / "featurelab-generation.json")
        return {
            "format": 1,
            "channel": "validation",
            "generation_manifest_sha256": manifest_sha,
            "properties": {
                "ro.product.device": "PJZ110",
                "ro.product.model": "PJZ110",
                "ro.build.version.sdk": "36",
                "ro.build.fingerprint": "synthetic/PJZ110/test:16/build:user/release-keys",
                "ro.build.version.incremental": "PJZ110_16.0.9.402",
                "ro.build.version.oplusrom": "V16.1.0",
            },
            "baselines": {
                "/my_product/vendor/etc/display.xml": "3" * 64,
            },
            "minimum_ksu_version_code": 12000,
            "minimum_ksu_kernel_version_code": 12000,
        }

    def _write_profile(self, mutate=None) -> None:
        value = self._profile_value()
        if mutate:
            mutate(value)
        self.profile.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _assemble(self, **kwargs):
        return assemble_validation_module(
            self.generated,
            self.profile,
            self.source,
            self.output,
            metadata=self.metadata,
            **kwargs,
        )

    def test_happy_directory_assembly(self) -> None:
        result = self._assemble()
        self.assertTrue(result["not_flash_ready"])
        self.assertTrue((self.output / "generated/mount-plan.tsv").is_file())
        self.assertTrue((self.output / "generated/file-metadata.tsv").is_file())
        self.assertIn("[VALIDATION ONLY]", (self.output / "module.prop").read_text())
        self.assertEqual((self.output / "generated/validation-only.flag").read_text().splitlines()[0], "NOT_FLASH_READY")
        self.assertTrue((self.output / "LICENSE").is_file())
        self.assertTrue((self.output / "THIRD_PARTY_NOTICES.md").is_file())

    def test_payload_metadata_is_preserved_for_installer(self) -> None:
        self._assemble()
        row = (self.output / "generated/file-metadata.tsv").read_text(encoding="utf-8").strip()
        self.assertEqual(
            row,
            "payload/my_product/vendor/etc/display.xml\t0\t0\t0644\tu:object_r:vendor_configs_file:s0",
        )
        customize = (self.output / "customize.sh").read_text(encoding="utf-8")
        self.assertIn('set_perm "$MODPATH/generated/$relative" "$uid" "$gid" "$mode" "$context"', customize)

    def test_invalid_source_metadata_is_rejected(self) -> None:
        def mutate(manifest):
            manifest["targets"]["/my_product/vendor/etc/display.xml"]["source_metadata"]["mode"] = "0777"
        self._rewrite_manifest(mutate)
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_raw_profile_values_are_not_packaged(self) -> None:
        self._assemble()
        package_bytes = b"\n".join(path.read_bytes() for path in self.output.rglob("*") if path.is_file())
        self.assertNotIn(b"synthetic/PJZ110/test", package_bytes)
        self.assertNotIn(b"PJZ110_16.0.9.402", package_bytes)
        compatibility = (self.output / "generated/compatibility.tsv").read_text()
        self.assertIn("ro.product.device\t", compatibility)
        self.assertNotIn("\tPJZ110", compatibility)

    def test_installer_contains_required_gates(self) -> None:
        self._assemble()
        script = (self.output / "customize.sh").read_text()
        for token in (
            "KSU:-false",
            "BOOTMODE:-false",
            "KSU_VER_CODE",
            "KSU_KERNEL_VER_CODE",
            "sha256sum -c generated/package-files.sha256",
            "generated/compatibility.tsv",
            'checked" -ge 5',
            "generated/file-metadata.tsv",
            "NOT_FLASH_READY",
        ):
            self.assertIn(token, script)

    def test_zip_requires_acknowledgement(self) -> None:
        with self.assertRaises(AssemblyError):
            self._assemble(zip_path=self.root / "module.zip")

    def test_deterministic_zip(self) -> None:
        zip_one = self.root / "one.zip"
        zip_two = self.root / "two.zip"
        self._assemble(zip_path=zip_one, acknowledge_test_only=True)
        second_output = self.root / "assembled-two"
        assemble_validation_module(
            self.generated,
            self.profile,
            self.source,
            second_output,
            metadata=self.metadata,
            zip_path=zip_two,
            acknowledge_test_only=True,
        )
        self.assertEqual(zip_one.read_bytes(), zip_two.read_bytes())
        with zipfile.ZipFile(zip_one) as archive:
            self.assertIn("module.prop", archive.namelist())
            self.assertIn("generated/mount-plan.tsv", archive.namelist())
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_manifest_binding_is_enforced(self) -> None:
        self._write_profile(lambda value: value.__setitem__("generation_manifest_sha256", "0" * 64))
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_baseline_mismatch_is_rejected(self) -> None:
        self._write_profile(lambda value: value["baselines"].__setitem__(
            "/my_product/vendor/etc/display.xml", "4" * 64
        ))
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_unexpected_generated_file_is_rejected(self) -> None:
        (self.generated / "unexpected.txt").write_text("bad", encoding="utf-8")
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_generated_symlink_is_rejected(self) -> None:
        link = self.generated / "leak"
        try:
            link.symlink_to(self.profile)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_failed_build_preserves_previous_output(self) -> None:
        self.output.mkdir()
        marker = self.output / "previous.txt"
        marker.write_text("keep", encoding="utf-8")
        (self.source / "LICENSE").unlink()
        with self.assertRaises(AssemblyError):
            self._assemble()
        self.assertEqual(marker.read_text(), "keep")

    def test_non_pass_audit_is_rejected(self) -> None:
        self._rewrite_manifest(lambda manifest: manifest.__setitem__("audit_verdict", "FAIL"))
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_property_plan_binding_and_synthetic_target(self) -> None:
        shutil.rmtree(self.generated)
        self.generated.mkdir()
        self._make_generated(with_property=True)
        self._write_profile()
        result = self._assemble()
        self.assertEqual(result["property_row_count"], 1)
        self.assertTrue((self.output / "generated/property-plan.tsv").is_file())

    def test_untracked_property_plan_is_rejected(self) -> None:
        (self.generated / "property-plan.tsv").write_text("unexpected\n", encoding="utf-8")
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_non_xml_target_is_rejected(self) -> None:
        original = "/my_product/vendor/etc/display.xml"
        bad = "/my_product/vendor/etc/display.conf"
        source = self.generated / original.lstrip("/")
        destination = self.generated / bad.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        def mutate(manifest):
            metadata = manifest["targets"].pop(original)
            manifest["targets"][bad] = metadata
            manifest["operations"][0]["target"] = bad
        self._rewrite_manifest(mutate)
        self._write_profile(lambda value: value.__setitem__("baselines", {bad: "3" * 64}))
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_output_cannot_consume_profile(self) -> None:
        with self.assertRaises(AssemblyError):
            assemble_validation_module(
                self.generated,
                self.profile,
                self.source,
                self.root,
                metadata=self.metadata,
            )

    def test_zip_cannot_be_inside_output(self) -> None:
        with self.assertRaises(AssemblyError):
            self._assemble(
                zip_path=self.output / "module.zip",
                acknowledge_test_only=True,
            )

    def test_output_cannot_be_parent_of_inputs(self) -> None:
        with self.assertRaises(AssemblyError):
            assemble_validation_module(
                self.generated,
                self.profile,
                self.source,
                self.root,
                metadata=self.metadata,
            )

    def test_zip_cannot_overwrite_profile_or_live_inside_inputs(self) -> None:
        for bad_zip in (self.profile, self.generated / "module.zip", self.source / "module.zip"):
            with self.subTest(path=bad_zip), self.assertRaises(AssemblyError):
                self._assemble(zip_path=bad_zip, acknowledge_test_only=True)

    def test_unselected_feature_operation_is_rejected(self) -> None:
        self._rewrite_manifest(lambda manifest: manifest["operations"][0].__setitem__(
            "feature_id", "display.unselected"
        ))
        with self.assertRaises(AssemblyError):
            self._assemble()

    def test_unknown_static_operation_is_rejected(self) -> None:
        self._rewrite_manifest(lambda manifest: manifest["operations"][0].__setitem__(
            "operation", "runtime_action"
        ))
        with self.assertRaises(AssemblyError):
            self._assemble()


if __name__ == "__main__":
    unittest.main()
