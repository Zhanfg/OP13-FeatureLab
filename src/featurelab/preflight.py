# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable

from .preflight_archive import PreflightArchiveError, sha256_file, verify_preflight_archive
from .preflight_evidence import ALLOWLISTED_PROPERTIES, classify_preflight_evidence


class PreflightAnalysisError(ValueError):
    """Raised when analysis cannot be completed safely."""


@dataclass(frozen=True)
class PreflightAnalysisResult:
    verdict: str
    output_path: Path
    archive_sha256: str
    blocker_count: int
    warning_count: int

    @property
    def exit_code(self) -> int:
        return 0 if self.verdict == "READY_FOR_CONTROLLED_VALIDATION" else 2

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.exit_code == 0,
            "verdict": self.verdict,
            "not_flash_ready": True,
            "output": str(self.output_path),
            "archive_sha256": self.archive_sha256,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
        }


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


def _validate_output_path(output_path: Path, archive_path: Path, sidecar_path: Path) -> tuple[Path, Path]:
    output_path = Path(output_path)
    archive_path = Path(archive_path).resolve(strict=True)
    sidecar_path = Path(sidecar_path).resolve(strict=True)
    if not output_path.is_absolute():
        raise PreflightAnalysisError("analysis output path must be absolute")
    if output_path == Path("/"):
        raise PreflightAnalysisError("analysis output cannot be filesystem root")
    lexical_output = Path(os.path.abspath(output_path))
    for source in (archive_path, sidecar_path):
        if lexical_output == source or source in lexical_output.parents or lexical_output in source.parents:
            raise PreflightAnalysisError("analysis output cannot overlap an input path")
    if output_path.exists() and (output_path.is_symlink() or not output_path.is_dir()):
        raise PreflightAnalysisError("existing analysis output must be a real directory")
    parent = output_path.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise PreflightAnalysisError("analysis output parent must be a pre-existing real directory")
    resolved_parent = parent.resolve(strict=True)
    resolved_output = resolved_parent / output_path.name
    for source in (archive_path, sidecar_path):
        if resolved_output == source or _is_relative_to(resolved_output, source) or _is_relative_to(source, resolved_output):
            raise PreflightAnalysisError("analysis output cannot overlap an input path")
    return resolved_output, resolved_parent


def _render_compatibility_getprop(properties: dict[str, str]) -> str:
    lines = []
    for key in ALLOWLISTED_PROPERTIES:
        value = properties.get(key, "")
        lines.append(f"[{key}]: [{value}]")
    return "\n".join(lines) + "\n"


def _write_atomic_output(
    output_path: Path,
    files: dict[str, bytes],
    *,
    replace: Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], None] = os.replace,
) -> None:
    parent = output_path.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.staging.", dir=parent))
    backup = parent / f".{output_path.name}.backup.{os.getpid()}"
    if backup.exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise PreflightAnalysisError(f"analysis backup path already exists: {backup}")
    old_moved = False
    new_committed = False
    try:
        for relative, data in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        directory_fd = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        if output_path.exists():
            replace(output_path, backup)
            old_moved = True
        replace(staging, output_path)
        new_committed = True
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        if old_moved:
            shutil.rmtree(backup)
    except Exception as exc:
        if new_committed and output_path.exists():
            shutil.rmtree(output_path, ignore_errors=True)
        if old_moved and backup.exists():
            try:
                replace(backup, output_path)
            except Exception as rollback_exc:
                raise PreflightAnalysisError(
                    "analysis output commit failed and previous output could not be restored"
                ) from rollback_exc
        raise PreflightAnalysisError("analysis output transaction failed") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and output_path.exists():
            shutil.rmtree(backup, ignore_errors=True)


def analyze_preflight_archive(
    archive_path: Path,
    sidecar_path: Path,
    output_path: Path,
    *,
    replace: Callable = os.replace,
) -> PreflightAnalysisResult:
    archive_path = Path(archive_path)
    sidecar_path = Path(sidecar_path)
    output_path, _parent = _validate_output_path(output_path, archive_path, sidecar_path)
    try:
        verified = verify_preflight_archive(archive_path, sidecar_path)
        classified = classify_preflight_evidence(verified)
    except PreflightArchiveError as exc:
        raise PreflightAnalysisError(str(exc)) from exc

    sidecar_sha256 = sha256_file(sidecar_path)
    compatibility_text = _render_compatibility_getprop(dict(classified.compatibility_properties))
    analysis = {
        "format": 1,
        "verdict": classified.verdict,
        "not_flash_ready": True,
        "archive": {
            "name": archive_path.name,
            "sha256": verified.archive_sha256,
            "sidecar_sha256": sidecar_sha256,
            "report_root": verified.report_root,
        },
        "device": {
            "property_sha256": dict(classified.property_hashes),
            "identity_status": classified.summary.get("identity_status", "missing"),
            "selinux_status": classified.summary.get("selinux_status", "missing"),
            "namespace_status": classified.summary.get("namespace_status", "missing"),
            "boot_id_sha256": hashlib.sha256(
                classified.summary.get("boot_id", "").encode("utf-8")
            ).hexdigest(),
        },
        "blockers": [finding.as_dict() for finding in classified.blockers],
        "warnings": [finding.as_dict() for finding in classified.warnings],
        "modules": [module.as_dict() for module in classified.modules],
        "overlay_conflicts": [conflict.as_dict() for conflict in classified.overlay_conflicts],
    }
    analysis_bytes = (
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    compatibility_bytes = compatibility_text.encode("utf-8")
    input_manifest_lines = [
        f"{verified.archive_sha256}  {archive_path.name}",
        f"{sidecar_sha256}  {sidecar_path.name}",
        f"{hashlib.sha256(analysis_bytes).hexdigest()}  analysis.json",
        f"{hashlib.sha256(compatibility_bytes).hexdigest()}  compatibility-getprop.private.txt",
    ]
    input_manifest = ("\n".join(input_manifest_lines) + "\n").encode("utf-8")
    _write_atomic_output(
        output_path,
        {
            "analysis.json": analysis_bytes,
            "compatibility-getprop.private.txt": compatibility_bytes,
            "preflight-inputs.sha256": input_manifest,
        },
        replace=replace,
    )
    return PreflightAnalysisResult(
        verdict=classified.verdict,
        output_path=output_path,
        archive_sha256=verified.archive_sha256,
        blocker_count=len(classified.blockers),
        warning_count=len(classified.warnings),
    )
