# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .assembly_policy import AssemblyError, ModuleMetadata

FORBIDDEN_FIELD_CHARS = "\t\r\n\x00"


def _reject_control(value: Any, label: str) -> None:
    if not isinstance(value, str) or any(char in value for char in FORBIDDEN_FIELD_CHARS):
        raise AssemblyError(f"{label} contains a forbidden control character")


def validate_assembly_control_fields(
    generated_root: Path,
    profile_path: Path,
    metadata: ModuleMetadata,
) -> None:
    for label, value in (
        ("module name", metadata.name),
        ("module version", metadata.version),
        ("module author", metadata.author),
        ("module description", metadata.description),
    ):
        _reject_control(value, label)

    try:
        manifest = json.loads((generated_root / "featurelab-generation.json").read_text(encoding="utf-8"))
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssemblyError(f"cannot inspect assembly control fields: {exc}") from exc

    if not isinstance(manifest, dict) or not isinstance(profile, dict):
        raise AssemblyError("assembly control inputs must be JSON objects")
    targets = manifest.get("targets")
    baselines = profile.get("baselines")
    if not isinstance(targets, dict) or not isinstance(baselines, dict):
        raise AssemblyError("assembly target maps must be JSON objects")
    for target in targets:
        _reject_control(target, "generation target")
    for target in baselines:
        _reject_control(target, "compatibility baseline target")
    operations = manifest.get("operations")
    if not isinstance(operations, list):
        raise AssemblyError("generation operations must be a list")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise AssemblyError(f"operation[{index}] must be an object")
        _reject_control(operation.get("target"), f"operation[{index}] target")


def _remove_directory(path: Path) -> None:
    if path.exists():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def commit_assembled_outputs(
    staging: Path,
    output: Path,
    zip_temporary: Path | None,
    zip_output: Path | None,
) -> None:
    output_backup = output.with_name(f".{output.name}.backup-{os.getpid()}")
    zip_backup = (
        zip_output.with_name(f".{zip_output.name}.backup-{os.getpid()}")
        if zip_output is not None
        else None
    )
    _remove_directory(output_backup)
    if zip_backup is not None:
        _remove_directory(zip_backup)

    output_backed = False
    zip_backed = False
    output_installed = False
    zip_installed = False
    try:
        if output.exists():
            os.replace(output, output_backup)
            output_backed = True
        if zip_output is not None:
            zip_output.parent.mkdir(parents=True, exist_ok=True)
            if zip_output.exists():
                assert zip_backup is not None
                os.replace(zip_output, zip_backup)
                zip_backed = True

        os.replace(staging, output)
        output_installed = True
        if zip_output is not None:
            if zip_temporary is None or not zip_temporary.is_file():
                raise OSError("prepared ZIP is missing")
            os.replace(zip_temporary, zip_output)
            zip_installed = True
    except OSError:
        if output_installed:
            _remove_directory(output)
        if output_backed and output_backup.exists():
            os.replace(output_backup, output)
        if zip_output is not None:
            if zip_installed:
                _remove_directory(zip_output)
            if zip_backed and zip_backup is not None and zip_backup.exists():
                os.replace(zip_backup, zip_output)
        raise

    _remove_directory(output_backup)
    if zip_backup is not None:
        _remove_directory(zip_backup)
