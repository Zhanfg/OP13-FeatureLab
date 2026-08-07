# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .assembly_policy import AssemblyError, SHA256_RE
from .util import atomic_write_json, sha256_file


def _load_analysis(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssemblyError(f"failed to load private preflight analysis {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AssemblyError("private preflight analysis root must be an object")
    return raw


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise AssemblyError(f"{label} must be a lowercase SHA-256")
    return value


def resolve_preflight_analysis(
    requested: Path | None,
    compatibility_profile_path: Path,
    *,
    protected_paths: tuple[Path, ...],
) -> Path | None:
    candidate = requested
    if candidate is None:
        automatic = compatibility_profile_path.parent / "analysis.json"
        if automatic.exists():
            candidate = automatic
    if candidate is None:
        return None

    candidate_path = Path(candidate)
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise AssemblyError(
            f"preflight analysis must be a regular non-symlink file: {candidate_path}"
        )
    resolved = candidate_path.resolve(strict=True)
    for protected in protected_paths:
        protected_resolved = protected.resolve()
        if (
            resolved == protected_resolved
            or resolved in protected_resolved.parents
            or protected_resolved in resolved.parents
        ):
            raise AssemblyError(
                f"preflight analysis overlaps a protected assembly path: {protected_resolved}"
            )
    return resolved


def validate_preflight_analysis(
    analysis_path: Path,
    compatibility_properties: Mapping[str, str],
) -> dict[str, Any]:
    original = Path(analysis_path)
    if original.is_symlink() or not original.is_file():
        raise AssemblyError("preflight analysis must be a regular non-symlink file")
    path = original.resolve(strict=True)
    raw = _load_analysis(path)

    if raw.get("format") != 1:
        raise AssemblyError("preflight analysis format must be 1")
    if raw.get("verdict") != "READY_FOR_CONTROLLED_VALIDATION":
        raise AssemblyError("preflight analysis is not ready for controlled validation")
    if raw.get("not_flash_ready") is not True:
        raise AssemblyError("preflight analysis must retain not_flash_ready=true")
    if raw.get("blockers") != []:
        raise AssemblyError("preflight analysis contains blockers")

    archive = raw.get("archive")
    device = raw.get("device")
    if not isinstance(archive, dict) or not isinstance(device, dict):
        raise AssemblyError("preflight analysis archive/device sections are missing")
    archive_sha = _sha(archive.get("sha256"), "preflight archive sha256")
    sidecar_sha = _sha(archive.get("sidecar_sha256"), "preflight sidecar sha256")
    property_hashes = device.get("property_sha256")
    if not isinstance(property_hashes, dict):
        raise AssemblyError("preflight property hash map is missing")

    normalized_hashes: dict[str, str] = {}
    if set(property_hashes) != set(compatibility_properties):
        missing = sorted(set(compatibility_properties) - set(property_hashes))
        extra = sorted(set(property_hashes) - set(compatibility_properties))
        raise AssemblyError(
            f"preflight property hash keys differ; missing={missing}, extra={extra}"
        )

    for key, value in sorted(compatibility_properties.items()):
        expected = _sha(
            property_hashes.get(key),
            f"preflight property hash for {key}",
        )
        actual = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if actual != expected:
            raise AssemblyError(f"preflight property hash mismatch: {key}")
        normalized_hashes[key] = expected

    canonical = json.dumps(
        normalized_hashes,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "format": 1,
        "verdict": "READY_FOR_CONTROLLED_VALIDATION",
        "not_flash_ready": True,
        "analysis_sha256": sha256_file(path),
        "archive_sha256": archive_sha,
        "sidecar_sha256": sidecar_sha,
        "compatibility_property_hashes_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }


def write_preflight_binding(
    staging: Path,
    binding: Mapping[str, Any],
) -> Path:
    destination = staging / "generated/preflight-binding.json"
    atomic_write_json(destination, dict(binding))
    return destination
