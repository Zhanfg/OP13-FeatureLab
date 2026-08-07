# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .assembly_files import (
    build_package_manifest,
    copy_project_runtime,
    create_deterministic_zip,
    write_compatibility_tsv,
    write_customize,
    write_module_prop,
    write_package_checksums,
)
from .assembly_hardening import commit_assembled_outputs, validate_assembly_control_fields
from .assembly_policy import (
    AssemblyError,
    ModuleMetadata,
    ValidatedGeneration,
    load_compatibility_profile,
    validate_generated_output,
    validate_path_isolation,
)
from .assembly_webui import copy_webui_assets
from .util import atomic_write_bytes, sha256_file


SAFE_MODULE_PERMISSION_BLOCK = r'''
# Do not recursively change webroot permissions or SELinux context. KernelSU
# manages the WebUI tree. Only project runtime and generated payloads are set.
set_perm "$MODPATH" 0 0 0755
[ ! -d "$MODPATH/generated" ] || set_perm_recursive "$MODPATH/generated" 0 0 0755 0644
[ ! -d "$MODPATH/scripts" ] || set_perm_recursive "$MODPATH/scripts" 0 0 0755 0755
[ ! -f "$MODPATH/module.prop" ] || set_perm "$MODPATH/module.prop" 0 0 0644
[ ! -f "$MODPATH/skip_mount" ] || set_perm "$MODPATH/skip_mount" 0 0 0644
[ ! -f "$MODPATH/LICENSE" ] || set_perm "$MODPATH/LICENSE" 0 0 0644
[ ! -f "$MODPATH/THIRD_PARTY_NOTICES.md" ] || set_perm "$MODPATH/THIRD_PARTY_NOTICES.md" 0 0 0644
'''

METADATA_PERMISSION_BLOCK = r'''
TAB="$(printf '\t')"
while IFS="$TAB" read -r relative uid gid mode context extra; do
  [ -n "$relative" ] || continue
  [ -z "$extra" ] || abort_install "Malformed file metadata row"
  case "$relative" in
    payload/*) ;;
    *) abort_install "Invalid payload metadata path" ;;
  esac
  case "$relative" in *"/../"*|../*|*/..|..) abort_install "Unsafe payload metadata path" ;; esac
  if [ "$context" = "-" ]; then
    set_perm "$MODPATH/generated/$relative" "$uid" "$gid" "$mode"
  else
    set_perm "$MODPATH/generated/$relative" "$uid" "$gid" "$mode" "$context"
  fi
done < generated/file-metadata.tsv
'''


def _metadata_row(target: str, relative: str, metadata: dict[str, Any]) -> str:
    source_metadata = metadata.get("source_metadata")
    if not isinstance(source_metadata, dict):
        raise AssemblyError(f"source metadata missing for {target}")
    mode_raw = source_metadata.get("mode")
    uid = source_metadata.get("uid")
    gid = source_metadata.get("gid")
    selinux = source_metadata.get("selinux")
    if not isinstance(mode_raw, str) or not mode_raw.startswith("0o"):
        raise AssemblyError(f"invalid source mode for {target}")
    try:
        mode_value = int(mode_raw, 8)
    except ValueError as exc:
        raise AssemblyError(f"invalid source mode for {target}") from exc
    if mode_value < 0 or mode_value > 0o7777:
        raise AssemblyError(f"source mode is out of range for {target}")
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 0:
        raise AssemblyError(f"invalid source uid for {target}")
    if not isinstance(gid, int) or isinstance(gid, bool) or gid < 0:
        raise AssemblyError(f"invalid source gid for {target}")
    if selinux is None:
        context = "-"
    elif isinstance(selinux, str) and selinux and all(char not in selinux for char in "\t\r\n\x00"):
        context = selinux
    else:
        raise AssemblyError(f"invalid SELinux context for {target}")
    mode = f"{mode_value:04o}"
    return f"{relative}\t{uid}\t{gid}\t{mode}\t{context}"


def _copy_generated_payload(
    generation: ValidatedGeneration,
    staging: Path,
) -> tuple[int, int]:
    generated_dir = staging / "generated"
    mount_rows: list[str] = []
    metadata_rows: list[str] = []
    sequence = 10

    for target in sorted(generation.targets):
        relative_target = target.lstrip("/")
        source = generation.root / relative_target
        package_relative = f"payload/{relative_target}"
        destination = generated_dir / package_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o644)

        owners = "+".join(generation.target_features[target])
        target_metadata = generation.targets[target]
        mount_rows.append(
            "\t".join(
                [
                    str(sequence),
                    owners,
                    package_relative,
                    target,
                    target_metadata["generated_sha256"],
                    target_metadata["baseline_sha256"],
                    "static-ro",
                ]
            )
        )
        metadata_rows.append(_metadata_row(target, package_relative, target_metadata))
        sequence += 10

    if not mount_rows:
        raise AssemblyError("validation module requires at least one static XML target")

    atomic_write_bytes(
        generated_dir / "mount-plan.tsv",
        ("\n".join(mount_rows) + "\n").encode("utf-8"),
        0o644,
    )
    atomic_write_bytes(
        generated_dir / "file-metadata.tsv",
        ("\n".join(metadata_rows) + "\n").encode("utf-8"),
        0o644,
    )

    shutil.copyfile(
        generation.manifest_path,
        generated_dir / "featurelab-generation.json",
    )
    os.chmod(generated_dir / "featurelab-generation.json", 0o644)

    property_rows = 0
    if generation.property_plan_path is not None:
        shutil.copyfile(
            generation.property_plan_path,
            generated_dir / "property-plan.tsv",
        )
        os.chmod(generated_dir / "property-plan.tsv", 0o644)
        metadata = generation.manifest["property_plan"]
        property_rows = int(metadata["row_count"])

    return len(mount_rows), property_rows


def _augment_customize_metadata(staging: Path) -> None:
    customize_path = staging / "customize.sh"
    content = customize_path.read_text(encoding="utf-8")
    marker = 'set_perm_recursive "$MODPATH" 0 0 0755 0644\n'
    if marker not in content:
        raise AssemblyError("customize template permission marker is missing")
    replacement = SAFE_MODULE_PERMISSION_BLOCK + METADATA_PERMISSION_BLOCK
    atomic_write_bytes(
        customize_path,
        content.replace(marker, replacement, 1).encode("utf-8"),
        0o755,
    )


def assemble_validation_module(
    generated_root: Path,
    compatibility_profile_path: Path,
    source_root: Path,
    output_dir: Path,
    *,
    metadata: ModuleMetadata,
    zip_path: Path | None = None,
    acknowledge_test_only: bool = False,
) -> dict[str, Any]:
    metadata.validate()
    generated, profile_path, source, output, zip_resolved = validate_path_isolation(
        generated_root,
        compatibility_profile_path,
        source_root,
        output_dir,
        zip_path,
    )
    if not source.is_dir():
        raise AssemblyError(f"source root does not exist: {source}")
    validate_assembly_control_fields(generated, profile_path, metadata)
    if zip_resolved is not None and not acknowledge_test_only:
        raise AssemblyError("ZIP creation requires explicit test-only acknowledgement")

    profile = load_compatibility_profile(profile_path)
    generation = validate_generated_output(generated, profile)

    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    zip_temporary: Path | None = None
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        copy_project_runtime(source, staging)
        webui = copy_webui_assets(source, staging, metadata.module_id)
        write_module_prop(staging, metadata)
        write_customize(staging, profile)
        target_count, property_row_count = _copy_generated_payload(generation, staging)
        _augment_customize_metadata(staging)
        write_compatibility_tsv(staging, profile)
        build_package_manifest(
            staging,
            metadata=metadata,
            profile=profile,
            generation_manifest_sha256=profile.generation_manifest_sha256,
            selected_features=list(generation.manifest["selected_features"]),
            target_count=target_count,
            property_row_count=property_row_count,
        )
        write_package_checksums(staging)

        if zip_resolved is not None:
            zip_temporary = zip_resolved.with_name(f".{zip_resolved.name}.assembled-{os.getpid()}")
            try:
                zip_temporary.unlink()
            except FileNotFoundError:
                pass
            create_deterministic_zip(staging, zip_temporary)

        commit_assembled_outputs(staging, output, zip_temporary, zip_resolved)

        return {
            "ok": True,
            "channel": "validation",
            "not_flash_ready": True,
            "output": str(output),
            "zip": str(zip_resolved) if zip_resolved is not None else None,
            "generation_manifest_sha256": profile.generation_manifest_sha256,
            "compatibility_profile_sha256": sha256_file(profile.path),
            "selected_features": list(generation.manifest["selected_features"]),
            "target_count": target_count,
            "property_row_count": property_row_count,
            "webui_included": bool(webui["included"]),
            "webui_file_count": int(webui["file_count"]),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AssemblyError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if zip_temporary is not None:
            try:
                zip_temporary.unlink()
            except FileNotFoundError:
                pass