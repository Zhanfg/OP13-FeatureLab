# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Iterable

from .assembly_policy import AssemblyError, CompatibilityProfile, ModuleMetadata
from .util import atomic_write_bytes, atomic_write_json, sha256_file

FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
REQUIRED_TEMPLATE_FILES = (
    "post-fs-data.sh",
    "post-mount.sh",
    "late-load.sh",
    "service.sh",
    "boot-completed.sh",
    "uninstall.sh",
)

CUSTOMIZE_TEMPLATE = r'''#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
SKIPUNZIP=0

abort_install() {
  ui_print "! $*"
  abort "$*"
}

ui_print "- OP13 FeatureLab validation package"
ui_print "- This package is NOT_FLASH_READY and is not a public release"

[ "${KSU:-false}" = "true" ] || abort_install "KernelSU installation is required"
[ "${BOOTMODE:-false}" = "true" ] || abort_install "Install from KernelSU Manager boot mode only"

case "${KSU_VER_CODE:-}" in
  ''|*[!0-9]*) abort_install "KSU_VER_CODE is unavailable or invalid" ;;
esac
case "${KSU_KERNEL_VER_CODE:-}" in
  ''|*[!0-9]*) abort_install "KSU_KERNEL_VER_CODE is unavailable or invalid" ;;
esac

[ "$KSU_VER_CODE" -ge __MIN_KSU__ ] || abort_install "KernelSU userspace is below the validated minimum"
[ "$KSU_KERNEL_VER_CODE" -ge __MIN_KERNEL__ ] || abort_install "KernelSU kernel component is below the validated minimum"

cd "$MODPATH" || abort_install "Cannot enter module directory"
sha256sum -c generated/package-files.sha256 >/dev/null 2>&1 \
  || abort_install "Module package checksum verification failed"

TAB="$(printf '\t')"
checked=0
while IFS="$TAB" read -r key expected extra; do
  [ -n "$key" ] || continue
  [ -z "$extra" ] || abort_install "Malformed compatibility row"
  current="$(getprop "$key")"
  actual="$(printf '%s' "$current" | sha256sum | awk '{print $1}')"
  [ "$actual" = "$expected" ] || abort_install "Device compatibility mismatch: $key"
  checked=$((checked + 1))
done < generated/compatibility.tsv

[ "$checked" -ge 5 ] || abort_install "Compatibility profile is incomplete"

set_perm_recursive "$MODPATH" 0 0 0755 0644
for script in \
  post-fs-data.sh post-mount.sh late-load.sh service.sh boot-completed.sh uninstall.sh \
  scripts/runtime/*.sh scripts/properties/*.sh; do
  [ -e "$MODPATH/$script" ] && set_perm "$MODPATH/$script" 0 0 0755
done

ui_print "- Compatibility checks passed for $checked device properties"
ui_print "- Installed validation-only package; real-device release gates remain open"
'''


def _copy_regular_file(source: Path, destination: Path, *, executable: bool | None = None) -> None:
    if source.is_symlink() or not source.is_file():
        raise AssemblyError(f"source must be a regular non-symlink file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    source_mode = stat.S_IMODE(source.stat().st_mode)
    if executable is True:
        mode = 0o755
    elif executable is False:
        mode = 0o644
    else:
        mode = 0o755 if source_mode & 0o111 else 0o644
    os.chmod(destination, mode)


def _copy_script_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise AssemblyError(f"required script directory is missing: {source}")
    for candidate in source.rglob("*"):
        relative = candidate.relative_to(source)
        if candidate.is_symlink():
            raise AssemblyError(f"source tree contains a symlink: {candidate}")
        if candidate.is_dir():
            (destination / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not candidate.is_file():
            raise AssemblyError(f"unsupported source entry: {candidate}")
        if candidate.suffix != ".sh":
            raise AssemblyError(f"runtime source tree contains a non-Shell file: {candidate}")
        _copy_regular_file(candidate, destination / relative, executable=True)


def copy_project_runtime(source_root: Path, staging: Path) -> None:
    template = source_root / "module-template"
    for name in REQUIRED_TEMPLATE_FILES:
        _copy_regular_file(template / name, staging / name, executable=True)
    _copy_script_tree(source_root / "scripts" / "runtime", staging / "scripts" / "runtime")
    _copy_script_tree(source_root / "scripts" / "properties", staging / "scripts" / "properties")
    _copy_regular_file(source_root / "LICENSE", staging / "LICENSE", executable=False)
    _copy_regular_file(
        source_root / "THIRD_PARTY_NOTICES.md",
        staging / "THIRD_PARTY_NOTICES.md",
        executable=False,
    )


def write_module_prop(staging: Path, metadata: ModuleMetadata) -> None:
    description = f"[VALIDATION ONLY] {metadata.description}"
    content = (
        f"id={metadata.module_id}\n"
        f"name={metadata.name}\n"
        f"version={metadata.version}\n"
        f"versionCode={metadata.version_code}\n"
        f"author={metadata.author}\n"
        f"description={description}\n"
    )
    atomic_write_bytes(staging / "module.prop", content.encode("utf-8"), 0o644)
    atomic_write_bytes(staging / "skip_mount", b"", 0o644)
    atomic_write_bytes(
        staging / "generated" / "validation-only.flag",
        b"NOT_FLASH_READY\nvalidation-channel-only\n",
        0o644,
    )


def write_customize(staging: Path, profile: CompatibilityProfile) -> None:
    content = (
        CUSTOMIZE_TEMPLATE.replace("__MIN_KSU__", str(profile.minimum_ksu_version_code))
        .replace("__MIN_KERNEL__", str(profile.minimum_ksu_kernel_version_code))
    )
    atomic_write_bytes(staging / "customize.sh", content.encode("utf-8"), 0o755)


def write_compatibility_tsv(staging: Path, profile: CompatibilityProfile) -> None:
    rows = []
    for key in sorted(profile.properties):
        digest = hashlib.sha256(profile.properties[key].encode("utf-8")).hexdigest()
        rows.append(f"{key}\t{digest}")
    atomic_write_bytes(
        staging / "generated" / "compatibility.tsv",
        ("\n".join(rows) + "\n").encode("utf-8"),
        0o644,
    )


def iter_package_files(root: Path, *, exclude: Iterable[str] = ()) -> list[Path]:
    excluded = set(exclude)
    files: list[Path] = []
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise AssemblyError(f"assembled package contains a symlink: {relative}")
        if candidate.is_file():
            if relative not in excluded:
                files.append(candidate)
        elif not candidate.is_dir():
            raise AssemblyError(f"assembled package contains an unsupported entry: {relative}")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def write_package_checksums(staging: Path) -> None:
    checksum_relative = "generated/package-files.sha256"
    rows = []
    for path in iter_package_files(staging, exclude={checksum_relative}):
        relative = path.relative_to(staging).as_posix()
        rows.append(f"{sha256_file(path)}  {relative}")
    atomic_write_bytes(
        staging / checksum_relative,
        ("\n".join(rows) + "\n").encode("utf-8"),
        0o644,
    )


def build_package_manifest(
    staging: Path,
    *,
    metadata: ModuleMetadata,
    profile: CompatibilityProfile,
    generation_manifest_sha256: str,
    selected_features: list[str],
    target_count: int,
    property_row_count: int,
) -> None:
    manifest = {
        "format": 1,
        "channel": "validation",
        "not_flash_ready": True,
        "module": {
            "id": metadata.module_id,
            "name": metadata.name,
            "version": metadata.version,
            "version_code": metadata.version_code,
        },
        "generation_manifest_sha256": generation_manifest_sha256,
        "compatibility_profile_sha256": sha256_file(profile.path),
        "selected_features": selected_features,
        "target_count": target_count,
        "property_row_count": property_row_count,
    }
    atomic_write_json(staging / "generated" / "package-manifest.json", manifest)


def create_deterministic_zip(module_root: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in iter_package_files(module_root):
                relative = path.relative_to(module_root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=FIXED_ZIP_DATE)
                mode = stat.S_IMODE(path.stat().st_mode)
                info.external_attr = ((stat.S_IFREG | mode) << 16)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, output_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
