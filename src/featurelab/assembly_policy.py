# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import sha256_file

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FEATURE_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
KNOWN_XML_OPERATIONS = {
    "xml_add",
    "xml_update",
    "xml_remove_exact",
    "list_append",
    "permission_add",
}
ALLOWED_STATIC_ROOTS = (
    "/system/",
    "/system_ext/",
    "/product/",
    "/vendor/",
    "/odm/",
    "/oem/",
    "/my_product/",
    "/my_region/",
    "/my_carrier/",
    "/my_company/",
    "/my_engineering/",
    "/my_heytap/",
    "/my_stock/",
    "/my_preload/",
    "/my_manifest/",
    "/my_bigball/",
)
REQUIRED_COMPAT_PROPERTIES = {
    "ro.product.device",
    "ro.product.model",
    "ro.build.version.sdk",
    "ro.build.fingerprint",
    "ro.build.version.incremental",
}
OPTIONAL_COMPAT_PROPERTIES = {
    "ro.product.name",
    "ro.product.manufacturer",
    "ro.build.version.oplusrom",
}
ALLOWED_COMPAT_PROPERTIES = REQUIRED_COMPAT_PROPERTIES | OPTIONAL_COMPAT_PROPERTIES


class AssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModuleMetadata:
    module_id: str
    name: str
    version: str
    version_code: int
    author: str
    description: str

    def validate(self) -> None:
        if not MODULE_ID_RE.fullmatch(self.module_id):
            raise AssemblyError(f"invalid module id: {self.module_id!r}")
        for label, value in (
            ("name", self.name),
            ("version", self.version),
            ("author", self.author),
            ("description", self.description),
        ):
            if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
                raise AssemblyError(f"invalid module {label}")
        if not isinstance(self.version_code, int) or isinstance(self.version_code, bool) or self.version_code <= 0:
            raise AssemblyError("version_code must be a positive integer")


@dataclass(frozen=True)
class CompatibilityProfile:
    path: Path
    generation_manifest_sha256: str
    properties: dict[str, str]
    baselines: dict[str, str]
    minimum_ksu_version_code: int
    minimum_ksu_kernel_version_code: int


@dataclass(frozen=True)
class ValidatedGeneration:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    targets: dict[str, dict[str, Any]]
    target_features: dict[str, list[str]]
    property_plan_path: Path | None
    expected_files: set[str]


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssemblyError(f"failed to load {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssemblyError(f"{label} root must be an object")
    return value


def _validate_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AssemblyError(f"{label} must be a lowercase SHA-256")
    return value


def _validate_nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AssemblyError(f"{label} must be a non-negative integer")
    return value


def load_compatibility_profile(path: Path) -> CompatibilityProfile:
    path = path.resolve()
    raw = _load_json_object(path, "compatibility profile")
    allowed = {
        "format",
        "channel",
        "generation_manifest_sha256",
        "properties",
        "baselines",
        "minimum_ksu_version_code",
        "minimum_ksu_kernel_version_code",
    }
    extra = set(raw) - allowed
    if extra:
        raise AssemblyError(f"unsupported compatibility profile fields: {', '.join(sorted(extra))}")
    if raw.get("format") != 1:
        raise AssemblyError("compatibility profile format must be 1")
    if raw.get("channel") != "validation":
        raise AssemblyError("only channel=validation is accepted before real-device release gates pass")
    generation_sha = _validate_sha(
        raw.get("generation_manifest_sha256"),
        "generation_manifest_sha256",
    )

    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise AssemblyError("compatibility profile properties must be an object")
    keys = set(properties)
    missing = REQUIRED_COMPAT_PROPERTIES - keys
    extra_properties = keys - ALLOWED_COMPAT_PROPERTIES
    if missing:
        raise AssemblyError(f"compatibility profile is missing: {', '.join(sorted(missing))}")
    if extra_properties:
        raise AssemblyError(f"unsupported compatibility properties: {', '.join(sorted(extra_properties))}")
    normalized_properties: dict[str, str] = {}
    for key, value in properties.items():
        if not isinstance(value, str) or not value or "\n" in value or "\r" in value or "\x00" in value:
            raise AssemblyError(f"invalid compatibility value for {key}")
        normalized_properties[key] = value

    baselines = raw.get("baselines")
    if not isinstance(baselines, dict):
        raise AssemblyError("compatibility profile baselines must be an object")
    normalized_baselines: dict[str, str] = {}
    for target, digest in baselines.items():
        if not isinstance(target, str) or not target.startswith("/") or ".." in Path(target.lstrip("/")).parts:
            raise AssemblyError(f"invalid baseline target: {target!r}")
        normalized_baselines[target] = _validate_sha(digest, f"baseline hash for {target}")

    return CompatibilityProfile(
        path=path,
        generation_manifest_sha256=generation_sha,
        properties=normalized_properties,
        baselines=normalized_baselines,
        minimum_ksu_version_code=_validate_nonnegative_int(
            raw.get("minimum_ksu_version_code", 0),
            "minimum_ksu_version_code",
        ),
        minimum_ksu_kernel_version_code=_validate_nonnegative_int(
            raw.get("minimum_ksu_kernel_version_code", 0),
            "minimum_ksu_kernel_version_code",
        ),
    )


def _safe_generated_file(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise AssemblyError(f"unsafe generated path: {relative!r}")
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AssemblyError(f"generated file is missing: {relative}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AssemblyError(f"generated file escapes root: {relative}") from exc
    if path.is_symlink() or not resolved.is_file():
        raise AssemblyError(f"generated path must be a regular non-symlink file: {relative}")
    return resolved


def _target_relative(target: str) -> str:
    if not target.startswith("/") or ".." in Path(target.lstrip("/")).parts:
        raise AssemblyError(f"invalid target path: {target!r}")
    if not target.endswith(".xml"):
        raise AssemblyError(f"static generated target must be XML: {target}")
    if not target.startswith(ALLOWED_STATIC_ROOTS):
        raise AssemblyError(f"unsupported static target root: {target}")
    return target.lstrip("/")


def validate_generated_output(
    generated_root: Path,
    profile: CompatibilityProfile,
) -> ValidatedGeneration:
    root = generated_root.resolve()
    if not root.is_dir():
        raise AssemblyError(f"generated output does not exist: {root}")
    manifest_path = _safe_generated_file(root, "featurelab-generation.json")
    if sha256_file(manifest_path) != profile.generation_manifest_sha256:
        raise AssemblyError("generation manifest hash does not match compatibility profile")
    manifest = _load_json_object(manifest_path, "generation manifest")
    if manifest.get("audit_verdict") != "PASS":
        raise AssemblyError("generation manifest audit_verdict is not PASS")

    selected = manifest.get("selected_features")
    if not isinstance(selected, list) or not selected:
        raise AssemblyError("generation manifest selected_features must be a non-empty list")
    selected_set: set[str] = set()
    for feature_id in selected:
        if not isinstance(feature_id, str) or not FEATURE_ID_RE.fullmatch(feature_id):
            raise AssemblyError(f"invalid selected feature id: {feature_id!r}")
        if feature_id in selected_set:
            raise AssemblyError(f"duplicate selected feature id: {feature_id}")
        selected_set.add(feature_id)

    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise AssemblyError("generation manifest targets must be an object")
    normalized_targets: dict[str, dict[str, Any]] = {}
    expected_files = {"featurelab-generation.json"}
    for target, metadata in targets.items():
        relative = _target_relative(target)
        if not isinstance(metadata, dict):
            raise AssemblyError(f"target metadata must be an object: {target}")
        baseline_sha = _validate_sha(metadata.get("baseline_sha256"), f"baseline hash for {target}")
        generated_sha = _validate_sha(metadata.get("generated_sha256"), f"generated hash for {target}")
        source_metadata = metadata.get("source_metadata")
        if not isinstance(source_metadata, dict):
            raise AssemblyError(f"source metadata missing for {target}")
        source = _safe_generated_file(root, relative)
        if sha256_file(source) != generated_sha:
            raise AssemblyError(f"generated target hash mismatch: {target}")
        normalized_targets[target] = {
            **metadata,
            "baseline_sha256": baseline_sha,
            "generated_sha256": generated_sha,
        }
        expected_files.add(relative)

    if set(profile.baselines) != set(normalized_targets):
        missing = set(normalized_targets) - set(profile.baselines)
        extra = set(profile.baselines) - set(normalized_targets)
        parts = []
        if missing:
            parts.append(f"missing baselines: {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unexpected baselines: {', '.join(sorted(extra))}")
        raise AssemblyError("; ".join(parts))
    for target, metadata in normalized_targets.items():
        if profile.baselines[target] != metadata["baseline_sha256"]:
            raise AssemblyError(f"compatibility baseline mismatch: {target}")

    operations = manifest.get("operations")
    if not isinstance(operations, list):
        raise AssemblyError("generation manifest operations must be a list")
    target_features: dict[str, set[str]] = {target: set() for target in normalized_targets}
    property_operations = 0
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise AssemblyError(f"operation[{index}] must be an object")
        operation_type = operation.get("operation")
        feature_id = operation.get("feature_id")
        target = operation.get("target")
        if feature_id not in selected_set:
            raise AssemblyError(f"operation[{index}] references an unselected feature: {feature_id!r}")
        if operation_type == "property_set":
            if target != "property-plan.tsv":
                raise AssemblyError("property_set operation must use target=property-plan.tsv")
            property_operations += 1
            continue
        if operation_type not in KNOWN_XML_OPERATIONS:
            raise AssemblyError(f"unknown static operation type: {operation_type!r}")
        if target not in normalized_targets:
            raise AssemblyError(f"operation target is absent from manifest targets: {target!r}")
        target_features[target].add(feature_id)

    for target, owners in target_features.items():
        if not owners:
            raise AssemblyError(f"generated target has no owning operation: {target}")

    property_metadata = manifest.get("property_plan")
    property_plan_path: Path | None = None
    if property_metadata is None:
        if property_operations:
            raise AssemblyError("property operations exist without property_plan metadata")
    else:
        if not isinstance(property_metadata, dict):
            raise AssemblyError("property_plan metadata must be an object or null")
        row_count = property_metadata.get("row_count")
        if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count <= 0:
            raise AssemblyError("property_plan row_count must be positive")
        if property_operations != row_count:
            raise AssemblyError("property operation count does not match property_plan row_count")
        plan_sha = _validate_sha(property_metadata.get("plan_sha256"), "property plan hash")
        property_plan_path = _safe_generated_file(root, "property-plan.tsv")
        if sha256_file(property_plan_path) != plan_sha:
            raise AssemblyError("property-plan.tsv hash mismatch")
        expected_files.add("property-plan.tsv")

    actual_files: set[str] = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise AssemblyError(f"generated output contains a symlink: {candidate.relative_to(root)}")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(root).as_posix())
        elif not candidate.is_dir():
            raise AssemblyError(f"unsupported generated entry: {candidate.relative_to(root)}")
    if actual_files != expected_files:
        extra = actual_files - expected_files
        missing = expected_files - actual_files
        parts = []
        if extra:
            parts.append(f"unexpected generated files: {', '.join(sorted(extra))}")
        if missing:
            parts.append(f"missing generated files: {', '.join(sorted(missing))}")
        raise AssemblyError("; ".join(parts))

    return ValidatedGeneration(
        root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        targets=normalized_targets,
        target_features={target: sorted(features) for target, features in target_features.items()},
        property_plan_path=property_plan_path,
        expected_files=expected_files,
    )


def validate_path_isolation(
    generated_root: Path,
    profile_path: Path,
    source_root: Path,
    output_dir: Path,
    zip_path: Path | None,
) -> tuple[Path, Path, Path, Path, Path | None]:
    generated = generated_root.resolve()
    profile = profile_path.resolve()
    source = source_root.resolve()
    output = output_dir.resolve()
    zip_resolved = zip_path.resolve() if zip_path is not None else None

    inputs = (generated, profile, source)
    for input_path in inputs:
        if output == input_path or output in input_path.parents or input_path in output.parents:
            raise AssemblyError(f"output directory overlaps an input path: {input_path}")
    if zip_resolved is not None:
        if zip_resolved == output or output in zip_resolved.parents:
            raise AssemblyError("ZIP output must not be inside the assembled module directory")
        for input_path in inputs:
            if zip_resolved == input_path or input_path in zip_resolved.parents or zip_resolved in input_path.parents:
                raise AssemblyError(f"ZIP output overlaps an input path: {input_path}")
    return generated, profile, source, output, zip_resolved
