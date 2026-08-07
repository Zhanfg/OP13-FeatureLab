# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .audit import AuditError, audit_trees, write_report
from .propertyplan import PropertyPlanError, build_property_plan, render_property_plan
from .util import atomic_write_bytes, atomic_write_json, mirrored_path, sha256_file, stat_metadata
from .xmlops import XmlOperationError, apply_xml_operation, parse_xml, write_xml


class GenerationError(RuntimeError):
    pass


PROHIBITED_TARGET_TOKEN = re.compile(r"(?:^|[/_.-])(camera|face|biometric)(?:[/_.-]|$)", re.IGNORECASE)
XML_OPERATION_TYPES = {"xml_add", "xml_update", "xml_remove_exact", "list_append", "permission_add"}
SUPPORTED_OPERATION_TYPES = XML_OPERATION_TYPES | {"property_set"}


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"failed to load catalog {path}: {exc}") from exc
    if not isinstance(value, list):
        raise GenerationError("catalog root must be a list")
    ids: set[str] = set()
    for index, feature in enumerate(value):
        if not isinstance(feature, dict):
            raise GenerationError(f"catalog feature[{index}] must be an object")
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or not feature_id:
            raise GenerationError(f"catalog feature[{index}] has invalid id")
        if feature_id in ids:
            raise GenerationError(f"duplicate feature id: {feature_id}")
        ids.add(feature_id)
        if feature.get("category") == "camera":
            raise GenerationError(f"camera category is prohibited: {feature_id}")
        operations = feature.get("operations", [])
        if not isinstance(operations, list):
            raise GenerationError(f"operations must be a list in {feature_id}")
        for operation in operations:
            if not isinstance(operation, dict):
                raise GenerationError(f"operation must be an object in {feature_id}")
            operation_type = operation.get("type")
            if operation_type not in SUPPORTED_OPERATION_TYPES:
                raise GenerationError(f"unsupported operation in {feature_id}: {operation_type}")
            if operation_type == "property_set":
                # Detailed property validation is centralized in propertyplan.py.
                if "target" in operation or "selector" in operation or "preserve_unrelated" in operation:
                    raise GenerationError(
                        f"property_set uses key/stage/apply_mode/restart, not target/selector, in {feature_id}"
                    )
                continue
            target = operation.get("target")
            selector = operation.get("selector")
            if not isinstance(target, str) or not target.startswith("/"):
                raise GenerationError(f"operation target must be absolute in {feature_id}")
            if not isinstance(selector, str) or not selector:
                raise GenerationError(f"operation selector must be a non-empty string in {feature_id}")
            if PROHIBITED_TARGET_TOKEN.search(target):
                raise GenerationError(f"camera/face/biometric target is prohibited in {feature_id}: {target}")
            if operation.get("preserve_unrelated") is not True:
                raise GenerationError(f"operation must declare preserve_unrelated=true in {feature_id}")
    return value


def _enabled_features(catalog: list[dict[str, Any]], selected: set[str] | None) -> list[dict[str, Any]]:
    if selected is None:
        return [feature for feature in catalog if feature.get("default_enabled") is True]
    missing = selected - {feature["id"] for feature in catalog}
    if missing:
        raise GenerationError(f"unknown selected feature ids: {', '.join(sorted(missing))}")
    return [feature for feature in catalog if feature["id"] in selected]


def generate_payload(
    baseline_root: Path,
    catalog_path: Path,
    output_root: Path,
    report_path: Path,
    *,
    selected_features: set[str] | None = None,
    property_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    baseline_root = baseline_root.resolve()
    output_root = output_root.resolve()
    if not baseline_root.is_dir():
        raise GenerationError(f"baseline root does not exist: {baseline_root}")
    if output_root == Path("/"):
        raise GenerationError("output root must not be the filesystem root")
    if output_root == baseline_root or baseline_root in output_root.parents:
        raise GenerationError("output root must not be inside the baseline root")

    catalog = _load_catalog(catalog_path)
    enabled = _enabled_features(catalog, selected_features)
    operations_by_target: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    property_operations: list[tuple[str, dict[str, Any]]] = []
    for feature in enabled:
        for operation in feature.get("operations", []):
            if operation["type"] == "property_set":
                property_operations.append((feature["id"], operation))
            else:
                operations_by_target[operation["target"]].append((feature["id"], operation))

    property_rows = []
    property_metadata: dict[str, Any] | None = None
    if property_operations:
        if property_snapshot_path is None:
            raise GenerationError("selected property_set operations require --property-snapshot")
        try:
            property_rows, property_metadata = build_property_plan(property_operations, property_snapshot_path)
        except PropertyPlanError as exc:
            raise GenerationError(str(exc)) from exc
    elif property_snapshot_path is not None and not property_snapshot_path.is_file():
        raise GenerationError(f"property snapshot does not exist: {property_snapshot_path}")

    staging = output_root.with_name(f".{output_root.name}.staging-{os.getpid()}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    generation_log: list[dict[str, Any]] = []
    allowed_removals: dict[str, set[str]] = defaultdict(set)
    metadata: dict[str, Any] = {}
    baseline_subset = staging.with_name(f".{output_root.name}.baseline-{os.getpid()}")
    try:
        for target, feature_operations in sorted(operations_by_target.items()):
            source = mirrored_path(baseline_root, target)
            destination = mirrored_path(staging, target)
            if not source.is_file():
                raise GenerationError(f"baseline target missing: {target}")
            if source.suffix.lower() != ".xml":
                raise GenerationError(
                    f"file operation target must be XML; properties use property_set/property-plan.tsv: {target}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            metadata[target] = {
                "baseline_sha256": sha256_file(source),
                "source_metadata": stat_metadata(source),
            }

            tree, declaration = parse_xml(source)
            for feature_id, operation in feature_operations:
                result = apply_xml_operation(tree, operation)
                generation_log.append(
                    {"feature_id": feature_id, "target": target, "operation": operation["type"], **result}
                )
                for key in result.get("removed_keys", []):
                    allowed_removals[target].add(str(key))
            write_xml(tree, destination, declaration=declaration)
            metadata[target]["generated_sha256"] = sha256_file(destination)

        # Audit only the touched baseline mirror against generated XML outputs.
        shutil.rmtree(baseline_subset, ignore_errors=True)
        baseline_subset.mkdir(parents=True)
        for target in operations_by_target:
            source = mirrored_path(baseline_root, target)
            destination = mirrored_path(baseline_subset, target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        audit_report = audit_trees(baseline_subset, staging, allowed_top_level_removals=allowed_removals)
        write_report(audit_report, report_path)
        shutil.rmtree(baseline_subset, ignore_errors=True)
        if audit_report.verdict != "PASS":
            raise GenerationError(f"semantic audit failed; see {report_path}")

        if property_rows:
            property_plan_path = staging / "property-plan.tsv"
            atomic_write_bytes(property_plan_path, render_property_plan(property_rows))
            assert property_metadata is not None
            property_metadata = {
                **property_metadata,
                "plan_sha256": sha256_file(property_plan_path),
            }
            generation_log.extend(
                {
                    "feature_id": row.feature_id,
                    "target": "property-plan.tsv",
                    "operation": "property_set",
                    "key": row.key,
                    "stage": row.stage,
                    "apply_mode": row.apply_mode,
                    "restart": row.restart,
                }
                for row in property_rows
            )

        manifest = {
            "catalog_sha256": sha256_file(catalog_path),
            "selected_features": [feature["id"] for feature in enabled],
            "targets": metadata,
            "property_plan": property_metadata,
            "operations": generation_log,
            "audit_verdict": audit_report.verdict,
        }
        atomic_write_json(staging / "featurelab-generation.json", manifest)
        backup = output_root.with_name(f".{output_root.name}.backup-{os.getpid()}")
        shutil.rmtree(backup, ignore_errors=True)
        if output_root.exists():
            os.replace(output_root, backup)
        try:
            os.replace(staging, output_root)
        except OSError:
            if backup.exists() and not output_root.exists():
                os.replace(backup, output_root)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return manifest
    except (OSError, ValueError, TypeError, XmlOperationError, AuditError, PropertyPlanError) as exc:
        raise GenerationError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        backup_path = output_root.with_name(f".{output_root.name}.backup-{os.getpid()}")
        shutil.rmtree(baseline_subset, ignore_errors=True)
        if backup_path.exists() and output_root.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
