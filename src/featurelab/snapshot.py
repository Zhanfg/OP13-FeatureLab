# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .propertyplan import (
    FEATURE_ID,
    PROPERTY_KEY,
    PropertyPlanError,
    _is_protected_key,
    scalar_to_property,
)
from .util import atomic_write_json, sha256_file

GETPROP_LINE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


class SnapshotError(RuntimeError):
    pass


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"failed to load catalog {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise SnapshotError("catalog root must be a list")

    identifiers: set[str] = set()
    for index, feature in enumerate(raw):
        if not isinstance(feature, dict):
            raise SnapshotError(f"catalog feature[{index}] must be an object")
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or not FEATURE_ID.fullmatch(feature_id):
            raise SnapshotError(f"invalid feature id at {index}: {feature_id!r}")
        if feature_id in identifiers:
            raise SnapshotError(f"duplicate feature id: {feature_id}")
        identifiers.add(feature_id)
        if not isinstance(feature.get("operations", []), list):
            raise SnapshotError(f"operations must be a list in {feature_id}")
    return raw


def selected_property_keys(catalog_path: Path, selected_features: set[str] | None) -> list[str]:
    catalog = _load_catalog(catalog_path)
    known = {feature["id"] for feature in catalog}
    if selected_features is None:
        enabled = [feature for feature in catalog if feature.get("default_enabled") is True]
    else:
        missing = selected_features - known
        if missing:
            raise SnapshotError(f"unknown selected feature ids: {', '.join(sorted(missing))}")
        enabled = [feature for feature in catalog if feature["id"] in selected_features]

    owners: dict[str, str] = {}
    for feature in enabled:
        feature_id = feature["id"]
        for operation in feature.get("operations", []):
            if not isinstance(operation, dict):
                raise SnapshotError(f"operation must be an object in {feature_id}")
            if operation.get("type") != "property_set":
                continue
            key = operation.get("key")
            if not isinstance(key, str) or not PROPERTY_KEY.fullmatch(key):
                raise SnapshotError(f"invalid property key in {feature_id}: {key!r}")
            if _is_protected_key(key):
                raise SnapshotError(f"protected property key in {feature_id}: {key}")
            if key in owners:
                raise SnapshotError(f"property key {key} is owned by both {owners[key]} and {feature_id}")
            owners[key] = feature_id
    return sorted(owners)


def parse_getprop_dump(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SnapshotError(f"failed to read getprop dump {path}: {exc}") from exc

    result: dict[str, str] = {}
    for line_number, raw in enumerate(lines, 1):
        if not raw:
            continue
        match = GETPROP_LINE.fullmatch(raw)
        if not match:
            raise SnapshotError(f"malformed getprop line {line_number}: {raw!r}")
        key, value = match.groups()
        if not PROPERTY_KEY.fullmatch(key):
            raise SnapshotError(f"invalid property key at line {line_number}: {key!r}")
        if key in result:
            raise SnapshotError(f"duplicate property key in getprop dump: {key}")
        try:
            result[key] = scalar_to_property(value)
        except PropertyPlanError as exc:
            raise SnapshotError(f"invalid value for {key}: {exc}") from exc
    return result


def capture_property_snapshot(
    catalog_path: Path,
    getprop_dump_path: Path,
    output_path: Path,
    *,
    selected_features: set[str] | None = None,
) -> dict[str, Any]:
    keys = selected_property_keys(catalog_path, selected_features)
    current = parse_getprop_dump(getprop_dump_path)

    properties: dict[str, dict[str, object]] = {}
    present_count = 0
    absent_count = 0
    for key in keys:
        if key in current:
            properties[key] = {"state": "present", "value": current[key]}
            present_count += 1
        else:
            properties[key] = {"state": "absent"}
            absent_count += 1

    payload = {"format": 1, "properties": properties}
    atomic_write_json(output_path, payload)
    return {
        "catalog_sha256": sha256_file(catalog_path),
        "getprop_dump_sha256": sha256_file(getprop_dump_path),
        "selected_features": sorted(selected_features) if selected_features is not None else None,
        "selected_keys": keys,
        "present_count": present_count,
        "absent_count": absent_count,
        "output_sha256": sha256_file(output_path),
    }
