# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Mapping

MAX_MEMBERS = 512
MAX_FILE_SIZE = 16 * 1024 * 1024
MAX_TOTAL_SIZE = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PreflightArchiveError(ValueError):
    """Raised when a private preflight archive cannot be trusted."""


@dataclass(frozen=True)
class VerifiedPreflightArchive:
    archive_path: Path
    archive_sha256: str
    report_root: str
    files: Mapping[str, bytes]

    def read_bytes(self, relative_path: str) -> bytes:
        try:
            return self.files[relative_path]
        except KeyError as exc:
            raise PreflightArchiveError(f"required archive member is missing: {relative_path}") from exc

    def read_text(self, relative_path: str) -> str:
        raw = self.read_bytes(relative_path)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PreflightArchiveError(f"archive member is not UTF-8: {relative_path}") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sidecar(sidecar_path: Path, archive_name: str) -> str:
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PreflightArchiveError(f"cannot read SHA-256 sidecar: {sidecar_path}") from exc

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise PreflightArchiveError("SHA-256 sidecar must contain exactly one non-empty line")
    parts = lines[0].split()
    if len(parts) != 2 or not _SHA256_RE.fullmatch(parts[0]):
        raise PreflightArchiveError("SHA-256 sidecar is malformed")
    listed_name = parts[1].removeprefix("*")
    if listed_name != archive_name:
        raise PreflightArchiveError(
            f"SHA-256 sidecar names {listed_name!r}, expected {archive_name!r}"
        )
    return parts[0]


def _safe_member_name(name: str) -> tuple[str, str]:
    if not name or "\x00" in name or "\\" in name:
        raise PreflightArchiveError(f"unsafe tar member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PreflightArchiveError(f"unsafe tar member path: {name!r}")
    if len(path.parts) == 1:
        return path.parts[0], ""
    return path.parts[0], PurePosixPath(*path.parts[1:]).as_posix()


def _parse_internal_manifest(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        if len(line) < 67 or line[64:66] != "  ":
            raise PreflightArchiveError(f"manifest line {line_number} is malformed")
        digest = line[:64]
        path_text = line[66:]
        if not _SHA256_RE.fullmatch(digest):
            raise PreflightArchiveError(f"manifest line {line_number} has an invalid digest")
        try:
            _, normalized = _safe_member_name(f"report/{path_text}")
        except PreflightArchiveError as exc:
            raise PreflightArchiveError(f"manifest line {line_number} has an unsafe path") from exc
        if normalized == "manifest.sha256":
            raise PreflightArchiveError("manifest must not list itself")
        if normalized in entries:
            raise PreflightArchiveError(f"manifest contains a duplicate path: {normalized}")
        entries[normalized] = digest
    if not entries:
        raise PreflightArchiveError("internal manifest is empty")
    return entries


def verify_preflight_archive(
    archive_path: Path,
    sidecar_path: Path,
    *,
    max_members: int = MAX_MEMBERS,
    max_file_size: int = MAX_FILE_SIZE,
    max_total_size: int = MAX_TOTAL_SIZE,
) -> VerifiedPreflightArchive:
    archive_path = Path(archive_path)
    sidecar_path = Path(sidecar_path)
    if not archive_path.is_file() or archive_path.is_symlink():
        raise PreflightArchiveError(f"archive must be a regular file: {archive_path}")
    if not sidecar_path.is_file() or sidecar_path.is_symlink():
        raise PreflightArchiveError(f"sidecar must be a regular file: {sidecar_path}")

    expected_digest = _parse_sidecar(sidecar_path, archive_path.name)
    actual_digest = sha256_file(archive_path)
    if actual_digest != expected_digest:
        raise PreflightArchiveError("external SHA-256 verification failed")

    files: dict[str, bytes] = {}
    roots: set[str] = set()
    seen_names: set[str] = set()
    total_size = 0

    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > max_members:
                raise PreflightArchiveError(
                    f"archive has {len(members)} members, limit is {max_members}"
                )
            for member in members:
                root, relative = _safe_member_name(member.name.rstrip("/"))
                roots.add(root)
                normalized_full = root if not relative else f"{root}/{relative}"
                if normalized_full in seen_names:
                    raise PreflightArchiveError(f"duplicate tar member: {normalized_full}")
                seen_names.add(normalized_full)

                if member.isdir():
                    continue
                if not relative:
                    raise PreflightArchiveError("report root must be a directory")
                if not member.isfile():
                    raise PreflightArchiveError(
                        f"unsupported tar member type for {normalized_full}"
                    )
                if member.size < 0 or member.size > max_file_size:
                    raise PreflightArchiveError(
                        f"archive member exceeds size limit: {normalized_full}"
                    )
                total_size += member.size
                if total_size > max_total_size:
                    raise PreflightArchiveError("archive exceeds total uncompressed size limit")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise PreflightArchiveError(f"cannot read tar member: {normalized_full}")
                data = extracted.read(max_file_size + 1)
                if len(data) != member.size or len(data) > max_file_size:
                    raise PreflightArchiveError(f"tar member size mismatch: {normalized_full}")
                if relative in files:
                    raise PreflightArchiveError(f"duplicate relative tar member: {relative}")
                files[relative] = data
    except (tarfile.TarError, OSError) as exc:
        if isinstance(exc, PreflightArchiveError):
            raise
        raise PreflightArchiveError("cannot parse preflight tar.gz archive") from exc

    if len(roots) != 1:
        raise PreflightArchiveError("archive must contain exactly one report root")
    root = next(iter(roots))
    manifest_raw = files.get("manifest.sha256")
    if manifest_raw is None:
        raise PreflightArchiveError("internal manifest.sha256 is missing")
    try:
        manifest_text = manifest_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightArchiveError("internal manifest.sha256 is not UTF-8") from exc
    manifest = _parse_internal_manifest(manifest_text)
    actual_paths = set(files) - {"manifest.sha256"}
    manifest_paths = set(manifest)
    missing = sorted(manifest_paths - actual_paths)
    extra = sorted(actual_paths - manifest_paths)
    if missing:
        raise PreflightArchiveError(f"manifest-listed files are missing: {missing}")
    if extra:
        raise PreflightArchiveError(f"archive contains unmanifested files: {extra}")
    for relative, expected in manifest.items():
        actual = sha256_bytes(files[relative])
        if actual != expected:
            raise PreflightArchiveError(f"internal manifest hash mismatch: {relative}")

    return VerifiedPreflightArchive(
        archive_path=archive_path,
        archive_sha256=actual_digest,
        report_root=root,
        files=files,
    )
