# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ZERO_SHA256 = "0" * 64
PROPERTY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
FEATURE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
STAGE_ORDER = {"early": 0, "service": 1, "boot-completed": 2}
VALID_MODES = {"direct", "trigger"}
VALID_RESTART = {"none", "service", "reboot"}
PROTECTED_KEY = re.compile(
    r"(?:^ctl\.|^sys\.powerctl$|^ro\.crypto\.|^vold\.|locksettings|gatekeeper|weaver|"
    r"synthetic[._]password|privacy[._]?password|privacypassword|keyguard|fingerprint|"
    r"biometric|camera)",
    re.IGNORECASE,
)
FACE_SENSITIVE_KEY = re.compile(
    r"(?:^|[._-])face(?:[._-][a-z0-9]+){0,6}[._-](?:unlock|enroll|detect|auth)(?:$|[._-])",
    re.IGNORECASE,
)


class PropertyPlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotValue:
    state: str
    value: str = ""


@dataclass(frozen=True)
class PropertyPlanRow:
    sequence: int
    feature_id: str
    stage: str
    key: str
    value: str
    baseline: SnapshotValue
    apply_mode: str
    restart: str

    @staticmethod
    def _sha(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _b64(value: str) -> str:
        if value == "":
            return "-"
        return base64.b64encode(value.encode("utf-8")).decode("ascii")

    def to_tsv(self) -> str:
        baseline_sha = self._sha(self.baseline.value) if self.baseline.state == "present" else ZERO_SHA256
        return "\t".join(
            [
                str(self.sequence),
                self.feature_id,
                self.stage,
                self.key,
                self._b64(self.value),
                self._sha(self.value),
                self.baseline.state,
                baseline_sha,
                self.apply_mode,
                self.restart,
            ]
        )


def _is_protected_key(key: str) -> bool:
    return PROTECTED_KEY.search(key) is not None or FACE_SENSITIVE_KEY.search(key) is not None


def scalar_to_property(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        raise PropertyPlanError("property value must be finite")
    if isinstance(value, (str, int, float)) and not isinstance(value, complex):
        result = str(value)
    else:
        raise PropertyPlanError(f"property value must be a scalar, got {type(value).__name__}")
    if "\x00" in result or "\n" in result or "\r" in result:
        raise PropertyPlanError("property value contains a forbidden control character")
    if len(result.encode("utf-8")) > 91:
        raise PropertyPlanError("property value exceeds Android's 91-byte limit")
    return result


def _load_snapshot(path: Path) -> dict[str, SnapshotValue]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PropertyPlanError(f"failed to load property snapshot {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != 1 or not isinstance(raw.get("properties"), dict):
        raise PropertyPlanError("property snapshot must be {format: 1, properties: {...}}")
    result: dict[str, SnapshotValue] = {}
    for key, entry in raw["properties"].items():
        if not isinstance(key, str) or not PROPERTY_KEY.fullmatch(key):
            raise PropertyPlanError(f"invalid snapshot property key: {key!r}")
        if _is_protected_key(key):
            raise PropertyPlanError(f"protected property key is forbidden in snapshot: {key}")
        if not isinstance(entry, dict) or set(entry) - {"state", "value"}:
            raise PropertyPlanError(f"invalid snapshot entry for {key}")
        state = entry.get("state")
        if state == "present":
            if "value" not in entry:
                raise PropertyPlanError(f"present snapshot entry lacks value: {key}")
            value = scalar_to_property(entry["value"])
            result[key] = SnapshotValue("present", value)
        elif state == "absent":
            if "value" in entry:
                raise PropertyPlanError(f"absent snapshot entry must not contain value: {key}")
            result[key] = SnapshotValue("absent", "")
        else:
            raise PropertyPlanError(f"invalid snapshot state for {key}: {state!r}")
    return result


def _validate_operation(feature_id: str, operation: dict[str, Any]) -> tuple[str, str, str, str, str]:
    if operation.get("type") != "property_set":
        raise PropertyPlanError("non-property operation passed to property planner")
    allowed = {"type", "key", "value", "stage", "apply_mode", "restart"}
    extra = set(operation) - allowed
    if extra:
        raise PropertyPlanError(f"unsupported property fields in {feature_id}: {', '.join(sorted(extra))}")
    key = operation.get("key")
    stage = operation.get("stage")
    mode = operation.get("apply_mode")
    restart = operation.get("restart")
    if not isinstance(key, str) or not PROPERTY_KEY.fullmatch(key):
        raise PropertyPlanError(f"invalid property key in {feature_id}: {key!r}")
    if _is_protected_key(key):
        raise PropertyPlanError(f"protected property key in {feature_id}: {key}")
    if stage not in STAGE_ORDER:
        raise PropertyPlanError(f"invalid property stage in {feature_id}: {stage!r}")
    if mode not in VALID_MODES:
        raise PropertyPlanError(f"invalid property apply mode in {feature_id}: {mode!r}")
    if restart not in VALID_RESTART:
        raise PropertyPlanError(f"invalid property restart policy in {feature_id}: {restart!r}")
    if stage == "early" and mode != "direct":
        raise PropertyPlanError(f"early property must use direct mode: {key}")
    if mode == "trigger" and restart == "none":
        raise PropertyPlanError(f"trigger property must declare service or reboot impact: {key}")
    value = scalar_to_property(operation.get("value"))
    return key, value, stage, mode, restart


def build_property_plan(
    feature_operations: Iterable[tuple[str, dict[str, Any]]],
    snapshot_path: Path,
) -> tuple[list[PropertyPlanRow], dict[str, Any]]:
    snapshot = _load_snapshot(snapshot_path)
    normalized: list[tuple[str, str, str, str, str, str]] = []
    seen: dict[str, str] = {}
    for feature_id, operation in feature_operations:
        if not FEATURE_ID.fullmatch(feature_id):
            raise PropertyPlanError(f"invalid feature ID: {feature_id!r}")
        key, value, stage, mode, restart = _validate_operation(feature_id, operation)
        if key in seen:
            raise PropertyPlanError(f"property key {key} is owned by both {seen[key]} and {feature_id}")
        seen[key] = feature_id
        if key not in snapshot:
            raise PropertyPlanError(f"property snapshot is missing selected key: {key}")
        normalized.append((stage, feature_id, key, value, mode, restart))

    normalized.sort(key=lambda item: (STAGE_ORDER[item[0]], item[1], item[2]))
    rows = [
        PropertyPlanRow(
            sequence=(index + 1) * 10,
            feature_id=feature_id,
            stage=stage,
            key=key,
            value=value,
            baseline=snapshot[key],
            apply_mode=mode,
            restart=restart,
        )
        for index, (stage, feature_id, key, value, mode, restart) in enumerate(normalized)
    ]
    metadata = {
        "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "selected_keys": [row.key for row in rows],
        "unused_snapshot_keys": sorted(set(snapshot) - set(seen)),
        "row_count": len(rows),
    }
    return rows, metadata


def render_property_plan(rows: Iterable[PropertyPlanRow]) -> bytes:
    lines = [row.to_tsv() for row in rows]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
