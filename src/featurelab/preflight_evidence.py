# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Mapping

from .preflight_archive import PreflightArchiveError, VerifiedPreflightArchive

ALLOWLISTED_PROPERTIES = (
    "ro.product.device",
    "ro.product.model",
    "ro.build.version.sdk",
    "ro.build.fingerprint",
    "ro.build.version.incremental",
    "ro.product.name",
    "ro.product.manufacturer",
    "ro.build.version.oplusrom",
)
REQUIRED_PROPERTIES = {
    "ro.product.device",
    "ro.product.model",
    "ro.build.version.sdk",
    "ro.build.fingerprint",
    "ro.build.version.incremental",
    "ro.build.version.oplusrom",
}
REQUIRED_COMMANDS = {
    "command:getprop-full",
    "command:ksud--version",
    "command:ksud-debug-version",
    "command:ksud-debug-info",
    "command:ksud-current-kmi",
    "command:ksud-module-list",
}
OPTIONAL_COMMANDS = {
    "command:ksud-debug-package",
    "command:ksud-feature-list",
}
PROTECTED_ROOTS = (
    "/system",
    "/system_ext",
    "/product",
    "/vendor",
    "/odm",
    "/oem",
    "/my_product",
    "/my_region",
    "/my_carrier",
    "/my_company",
)
_MODULE_PATH_RE = re.compile(
    r"/(?:data/adb/modules|debug_ramdisk/\.magisk/modules|data/adb/modules_update)/([A-Za-z0-9._-]+)(?:/|$)"
)
_GETPROP_RE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ModuleState:
    module_id: str
    disabled: bool
    remove: bool
    update: bool
    skip_mount: bool
    module_prop_sha256: str
    webroot: bool

    @property
    def active(self) -> bool:
        return not self.disabled and not self.remove

    def as_dict(self) -> dict[str, object]:
        return {
            "module_id": self.module_id,
            "disabled": self.disabled,
            "remove": self.remove,
            "update": self.update,
            "skip_mount": self.skip_mount,
            "module_prop_sha256": self.module_prop_sha256,
            "webroot": self.webroot,
            "active": self.active,
        }


@dataclass(frozen=True)
class OverlayConflict:
    module_id: str
    target: str
    source_line_sha256: str
    inventory_state: str

    def as_dict(self) -> dict[str, str]:
        return {
            "module_id": self.module_id,
            "target": self.target,
            "source_line_sha256": self.source_line_sha256,
            "inventory_state": self.inventory_state,
        }


@dataclass(frozen=True)
class ClassifiedEvidence:
    blockers: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    compatibility_properties: Mapping[str, str]
    property_hashes: Mapping[str, str]
    modules: tuple[ModuleState, ...]
    overlay_conflicts: tuple[OverlayConflict, ...]
    summary: Mapping[str, str]

    @property
    def verdict(self) -> str:
        return "BLOCKED" if self.blockers else "READY_FOR_CONTROLLED_VALIDATION"


def _strict_tsv(text: str, expected_header: tuple[str, ...], label: str) -> list[tuple[str, ...]]:
    lines = text.splitlines()
    if not lines:
        raise PreflightArchiveError(f"{label} is empty")
    header = tuple(lines[0].split("\t"))
    if header != expected_header:
        raise PreflightArchiveError(f"{label} has an unexpected header")
    rows: list[tuple[str, ...]] = []
    for line_number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        parts = tuple(line.split("\t"))
        if len(parts) != len(expected_header):
            raise PreflightArchiveError(f"{label} line {line_number} has the wrong column count")
        if any("\x00" in part or "\r" in part or "\n" in part for part in parts):
            raise PreflightArchiveError(f"{label} line {line_number} contains a control character")
        rows.append(parts)
    return rows


def _key_value_tsv(text: str, label: str) -> dict[str, str]:
    rows = _strict_tsv(text, ("field", "value"), label)
    values: dict[str, str] = {}
    for key, value in rows:
        if not key or key in values:
            raise PreflightArchiveError(f"{label} contains a duplicate or empty key: {key!r}")
        values[key] = value
    return values


def _properties_tsv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise PreflightArchiveError(
                f"compatibility-properties.tsv line {line_number} is malformed"
            )
        key, value = parts
        if key not in ALLOWLISTED_PROPERTIES:
            raise PreflightArchiveError(f"unexpected compatibility property: {key}")
        if key in values:
            raise PreflightArchiveError(f"duplicate compatibility property: {key}")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise PreflightArchiveError(f"invalid compatibility property value: {key}")
        values[key] = value
    missing_keys = set(ALLOWLISTED_PROPERTIES) - set(values)
    if missing_keys:
        raise PreflightArchiveError(
            f"compatibility property rows are missing: {sorted(missing_keys)}"
        )
    return values


def _command_statuses(text: str) -> dict[str, str]:
    rows = _strict_tsv(text, ("name", "status", "detail"), "checks/status.tsv")
    result: dict[str, str] = {}
    for name, status, _detail in rows:
        if not name or name in result:
            raise PreflightArchiveError(f"checks/status.tsv has a duplicate or empty name: {name!r}")
        result[name] = status
    return result


def _modules(text: str) -> tuple[ModuleState, ...]:
    rows = _strict_tsv(
        text,
        (
            "module_id",
            "disabled",
            "remove",
            "update",
            "skip_mount",
            "module_prop_sha256",
            "webroot",
        ),
        "kernelsu/modules.tsv",
    )
    modules: list[ModuleState] = []
    seen: set[str] = set()
    for row in rows:
        module_id, disabled, remove, update, skip_mount, prop_hash, webroot = row
        if not re.fullmatch(r"[A-Za-z0-9._-]+", module_id) or module_id in seen:
            raise PreflightArchiveError(f"invalid or duplicate module ID: {module_id!r}")
        flags = (disabled, remove, update, skip_mount, webroot)
        if any(flag not in {"0", "1"} for flag in flags):
            raise PreflightArchiveError(f"module {module_id} contains an invalid state flag")
        if prop_hash and not re.fullmatch(r"[0-9a-f]{64}", prop_hash):
            raise PreflightArchiveError(f"module {module_id} contains an invalid module.prop hash")
        seen.add(module_id)
        modules.append(
            ModuleState(
                module_id=module_id,
                disabled=disabled == "1",
                remove=remove == "1",
                update=update == "1",
                skip_mount=skip_mount == "1",
                module_prop_sha256=prop_hash,
                webroot=webroot == "1",
            )
        )
    return tuple(modules)


def _parse_getprop(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _GETPROP_RE.fullmatch(line)
        if not match:
            continue
        key, value = match.groups()
        if key in values:
            raise PreflightArchiveError(f"full getprop contains a duplicate key: {key}")
        values[key] = value
    return values


def _mount_point(line: str) -> str | None:
    fields = line.split()
    if "-" not in fields:
        return None
    separator = fields.index("-")
    if separator < 5:
        return None
    return fields[4].replace("\\040", " ")


def _protected_target(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in PROTECTED_ROOTS)


def _overlay_conflicts(
    mountinfo_text: str,
    inventory: Mapping[str, ModuleState],
) -> tuple[OverlayConflict, ...]:
    conflicts: list[OverlayConflict] = []
    seen: set[tuple[str, str, str]] = set()
    for line in mountinfo_text.splitlines():
        target = _mount_point(line)
        if not target or not _protected_target(target):
            continue
        matches = sorted(set(_MODULE_PATH_RE.findall(line)))
        for module_id in matches:
            state = inventory.get(module_id)
            if state is None:
                inventory_state = "unknown-inventory"
            elif state.active:
                inventory_state = "active"
            else:
                inventory_state = "inactive-but-mounted"
            line_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
            key = (module_id, target, line_hash)
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(
                OverlayConflict(
                    module_id=module_id,
                    target=target,
                    source_line_sha256=line_hash,
                    inventory_state=inventory_state,
                )
            )
    return tuple(conflicts)


def classify_preflight_evidence(verified: VerifiedPreflightArchive) -> ClassifiedEvidence:
    summary = _key_value_tsv(verified.read_text("summary.tsv"), "summary.tsv")
    properties = _properties_tsv(verified.read_text("device/compatibility-properties.tsv"))
    statuses = _command_statuses(verified.read_text("checks/status.tsv"))
    modules = _modules(verified.read_text("kernelsu/modules.tsv"))
    inventory = {module.module_id: module for module in modules}
    conflicts = _overlay_conflicts(
        verified.read_text("mounts/init-mountinfo.txt"), inventory
    )
    full_getprop = _parse_getprop(verified.read_text("device/getprop.private.txt"))

    blockers: list[Finding] = []
    warnings: list[Finding] = []

    expected_summary = {
        "report_format": "1",
        "collector_mode": "read-only-preflight",
        "not_flash_ready": "true",
        "uid": "0",
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            blockers.append(Finding("collector.summary_mismatch", f"{key} must equal {expected}"))

    if summary.get("identity_status") != "PASS":
        blockers.append(Finding("device.collector_identity_failed", "collector identity gate did not pass"))
    if properties.get("ro.product.device") != "PJZ110":
        blockers.append(Finding("device.unsupported_product", "ro.product.device is not PJZ110"))
    if properties.get("ro.build.version.sdk") != "36":
        blockers.append(Finding("device.unsupported_sdk", "Android SDK is not 36"))
    if not properties.get("ro.build.version.oplusrom", "").startswith("V16.1"):
        blockers.append(Finding("device.unsupported_oplus_rom", "OPlus ROM is outside V16.1*"))
    for key in sorted(REQUIRED_PROPERTIES):
        if not properties.get(key):
            blockers.append(Finding("device.missing_property", f"required property is empty: {key}"))

    if summary.get("selinux_status") != "ENFORCING":
        blockers.append(Finding("security.selinux_not_enforcing", "SELinux is not Enforcing"))
    if not summary.get("boot_id"):
        blockers.append(Finding("kernel.boot_id_missing", "kernel boot ID is missing"))
    if not summary.get("ksud_path"):
        blockers.append(Finding("kernelsu.ksud_missing", "ksud executable path is missing"))

    for command in sorted(REQUIRED_COMMANDS):
        if statuses.get(command) != "0":
            blockers.append(Finding("kernelsu.required_query_failed", command))
    for command in sorted(OPTIONAL_COMMANDS):
        status = statuses.get(command)
        if status is None or status != "0":
            warnings.append(Finding("kernelsu.optional_query_failed", command))

    if summary.get("namespace_status") != "SAME":
        warnings.append(
            Finding(
                "mount.namespace_differs",
                f"collector namespace status is {summary.get('namespace_status', 'missing')}",
            )
        )

    tainted = verified.read_text("kernel/tainted.txt").strip()
    if tainted and tainted != "0":
        warnings.append(Finding("kernel.tainted", f"kernel taint value is {tainted}"))

    verified_boot = full_getprop.get("ro.boot.verifiedbootstate", "")
    if verified_boot.lower() != "green":
        warnings.append(
            Finding(
                "boot.verified_state_not_green",
                f"ro.boot.verifiedbootstate is {verified_boot or 'missing'}",
            )
        )

    for conflict in conflicts:
        blockers.append(
            Finding(
                "modules.protected_overlay",
                f"{conflict.module_id} ({conflict.inventory_state}) overlays {conflict.target}",
            )
        )

    property_hashes = {
        key: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key, value in properties.items()
    }
    return ClassifiedEvidence(
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        compatibility_properties=properties,
        property_hashes=property_hashes,
        modules=modules,
        overlay_conflicts=conflicts,
        summary=summary,
    )
