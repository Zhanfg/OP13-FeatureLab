# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from featurelab.assembly_policy import AssemblyError
import test_module_assembler as fixture_module


class ModuleAssemblerHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixture_module.ModuleAssemblerTests("test_happy_directory_assembly")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_zip_commit_failure_restores_previous_directory_and_zip(self) -> None:
        fixture = self.fixture
        fixture.output.mkdir()
        (fixture.output / "previous.txt").write_text("old-directory", encoding="utf-8")
        zip_path = fixture.root / "module.zip"
        zip_path.write_bytes(b"old-zip")
        original_replace = os.replace

        def fail_final_zip(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if source_path.name.startswith(".module.zip.assembled-") and destination_path == zip_path:
                raise OSError("injected ZIP commit failure")
            return original_replace(source, destination)

        with mock.patch("featurelab.assembly_hardening.os.replace", side_effect=fail_final_zip):
            with self.assertRaises(AssemblyError):
                fixture._assemble(zip_path=zip_path, acknowledge_test_only=True)

        self.assertEqual(
            (fixture.output / "previous.txt").read_text(encoding="utf-8"),
            "old-directory",
        )
        self.assertEqual(zip_path.read_bytes(), b"old-zip")

    def test_target_control_characters_are_rejected(self) -> None:
        fixture = self.fixture
        original = "/my_product/vendor/etc/display.xml"
        bad = "/my_product/vendor/etc/display.xml\nsecond"

        def mutate(manifest):
            metadata = manifest["targets"].pop(original)
            manifest["targets"][bad] = metadata
            manifest["operations"][0]["target"] = bad

        fixture._rewrite_manifest(mutate)
        fixture._write_profile(
            lambda value: value.__setitem__("baselines", {bad: "3" * 64})
        )
        with self.assertRaises(AssemblyError):
            fixture._assemble()


if __name__ == "__main__":
    unittest.main()
