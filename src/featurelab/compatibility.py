# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .assembly_policy import (
    ALLOWED_STATIC_ROOTS,
    OPTIONAL_COMPAT_PROPERTIES,
    REQUIRED_COMPAT_PROPERTIES,
    SHA256_RE,
)
from .util import atomic_write_json, sha256_file


class CompatibilityBuildError(RuntimeError):
    pass


GETPROP_LINE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


def _read_allowlisted_getprop(path: Path, wanted: set[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CompatibilityBuildError(f"failed to read getprop dump {path}: {exc}") from exc
    found: dict[str, str] = {}
    seen: set[str] = set()
    for line_number, raw in enumerate(lines, 1):
        if not raw:
            continue
        match = GETPROP_LINE.fullmatch(raw)
        if not match:
            raise CompatibilityBuildError(f"malformed getprop line {line_number}: {raw!r}")
        key, value = match.groups()
        if key in seen:
            raise CompatibilityBuildError(f"duplicate property key in getprop dump: {key}")
        seen.add(key)
        if key in wanted:
            if any(char in value for char in "\r\n\x00"):
                raise CompatibilityBuildError(f"invalid compatibility value for {key}")
            found[key] = value
    return found


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompatibilityBuildError(f"failed to load generation manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompatibilityBuildError("generation manifest root must be an object")
    return value


def _nonnegative(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CompatibilityBuildError(f"{label} must be a non-negative integer")
    return value


def _validate_target(target: Any) -> str:
    if not isinstance(target, str) or any(char in target for char in "\t\r\n\x00"):
        raise CompatibilityBuildError(f"invalid generation target: {target!r}")
    if not target.startswith("/") or ".." in Path(target.lstrip("/")).parts:
        raise CompatibilityBuildError(f"invalid generation target: {target!r}")
    if not target.endswith(".xml") or not target.startswith(ALLOWED_STATIC_ROOTS):
        raise CompatibilityBuildError(f"unsupported generation target: {target}")
    return target


def build_compatibility_profile(
    generation_manifest_path: Path,
    getprop_dump_path: Path,
    output_path: Path,
    *,
    minimum_ksu_version_code: int,
    minimum_ksu_kernel_version_code: int,
    expected_device: str = "PJZ110",
    expected_sdk: str = "36",
    expected_oplus_rom_prefix: str = "V16.1",
) -> dict[str, Any]:
    manifest_path = generation_manifest_path.resolve()
    dump_path = getprop_dump_path.resolve()
    output = output_path.resolve()
    if output == manifest_path or output == dump_path:
        raise CompatibilityBuildError("compatibility output must not overwrite an input")
    generated_root = manifest_path.parent
    if output == generated_root or output.parent == generated_root or generated_root in output.parents:
        raise CompatibilityBuildError("compatibility output must stay outside the generated output tree")

    minimum_ksu_version_code = _nonnegative(
        minimum_ksu_version_code,
        "minimum_ksu_version_code",
    )
    minimum_ksu_kernel_version_code = _nonnegative(
        minimum_ksu_kernel_version_code,
        "minimum_ksu_kernel_version_code",
    )
    for label, value in (
        ("expected_device", expected_device),
        ("expected_sdk", expected_sdk),
        ("expected_oplus_rom_prefix", expected_oplus_rom_prefix),
    ):
        if not isinstance(value, str) or not value or any(char in value for char in "\t\r\n\x00"):
            raise CompatibilityBuildError(f"{label} must be a non-empty control-free string")

    manifest = _load_manifest(manifest_path)
    if manifest.get("audit_verdict") != "PASS":
        raise CompatibilityBuildError("generation manifest audit_verdict is not PASS")
    selected = manifest.get("selected_features")
    if not isinstance(selected, list) or not selected:
        raise CompatibilityBuildError("generation manifest has no selected features")
    targets = manifest.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise CompatibilityBuildError("generation manifest has no static targets")

    baselines: dict[str, str] = {}
    for raw_target, metadata in targets.items():
        target = _validate_target(raw_target)
        if not isinstance(metadata, dict):
            raise CompatibilityBuildError(f"target metadata must be an object: {target}")
        digest = metadata.get("baseline_sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise CompatibilityBuildError(f"invalid baseline hash for {target}")
        baselines[target] = digest

    wanted_properties = REQUIRED_COMPAT_PROPERTIES | OPTIONAL_COMPAT_PROPERTIES
    current = _read_allowlisted_getprop(dump_path, wanted_properties)

    missing = [key for key in sorted(REQUIRED_COMPAT_PROPERTIES) if not current.get(key)]
    if missing:
        raise CompatibilityBuildError(f"required device properties are missing: {', '.join(missing)}")
    if current["ro.product.device"] != expected_device:
        raise CompatibilityBuildError(
            f"unexpected device: {current['ro.product.device']!r}; expected {expected_device!r}"
        )
    if current["ro.build.version.sdk"] != expected_sdk:
        raise CompatibilityBuildError(
            f"unexpected SDK: {current['ro.build.version.sdk']!r}; expected {expected_sdk!r}"
        )
    oplus_rom = current.get("ro.build.version.oplusrom", "")
    if not oplus_rom.startswith(expected_oplus_rom_prefix):
        raise CompatibilityBuildError(
            f"unexpected OPlus ROM version: {oplus_rom!r}; expected prefix {expected_oplus_rom_prefix!r}"
        )

    properties: dict[str, str] = {
        key: current[key]
        for key in sorted(REQUIRED_COMPAT_PROPERTIES)
    }
    for key in sorted(OPTIONAL_COMPAT_PROPERTIES):
        value = current.get(key)
        if value:
            properties[key] = value

    payload = {
        "format": 1,
        "channel": "validation",
        "generation_manifest_sha256": sha256_file(manifest_path),
        "properties": properties,
        "baselines": dict(sorted(baselines.items())),
        "minimum_ksu_version_code": minimum_ksu_version_code,
        "minimum_ksu_kernel_version_code": minimum_ksu_kernel_version_code,
    }
    atomic_write_json(output, payload)
    return {
        "ok": True,
        "channel": "validation",
        "output_sha256": sha256_file(output),
        "generation_manifest_sha256": payload["generation_manifest_sha256"],
        "property_keys": sorted(properties),
        "target_count": len(baselines),
        "minimum_ksu_version_code": minimum_ksu_version_code,
        "minimum_ksu_kernel_version_code": minimum_ksu_kernel_version_code,
    }
