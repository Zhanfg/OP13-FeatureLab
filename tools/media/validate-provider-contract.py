#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate provider-neutral media dependency, namespace, and target-platform contracts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
EDGE_TYPES = {
    "elf-dt-needed",
    "elf-dlopen-candidate",
    "init-exec",
    "init-interface",
    "vintf-instance",
    "media-codec-include",
    "codec-component-library",
    "audio-effect-library",
    "config-file-reference",
    "property-trigger",
    "selinux-context-requirement",
}
ELF_EDGES = {"elf-dt-needed", "elf-dlopen-candidate", "codec-component-library", "audio-effect-library"}


def fail(message: str) -> None:
    raise ValueError(message)


def require_hash_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty array")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not HASH_RE.fullmatch(item):
            fail(f"{label} contains an invalid SHA-256")
        if item in seen:
            fail(f"{label} contains duplicate SHA-256 values")
        seen.add(item)
    return value


def parse_time(value: object, max_age_days: int) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail("generated_at_utc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("generated_at_utc is invalid") from exc
    now = dt.datetime.now(dt.timezone.utc)
    if parsed > now + dt.timedelta(minutes=5):
        fail("generated_at_utc is in the future")
    if max_age_days >= 0 and now - parsed > dt.timedelta(days=max_age_days):
        fail(f"contract is older than {max_age_days} days")
    return parsed.isoformat().replace("+00:00", "Z")


def validate_edge(row: object, index: int) -> tuple[str, str]:
    label = f"edges[{index}]"
    if not isinstance(row, dict):
        fail(f"{label} must be an object")
    edge_id = row.get("edge_id")
    edge_type = row.get("edge_type")
    if not isinstance(edge_id, str) or not edge_id:
        fail(f"{label}.edge_id must be non-empty")
    if edge_type not in EDGE_TYPES:
        fail(f"{label}.edge_type is invalid")
    for key in ("consumer", "requirement"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            fail(f"{label}.{key} must be non-empty")
    require_hash_list(row.get("evidence_sha256"), f"{label}.evidence_sha256")

    resolution = row.get("resolution")
    if resolution not in {"static-resolved", "declarative-resolved", "observed-runtime", "unresolved", "candidate"}:
        fail(f"{label}.resolution is invalid")

    if edge_type in ELF_EDGES:
        architecture = row.get("architecture")
        soname = row.get("soname")
        symbol_abi = row.get("symbol_abi")
        namespace = row.get("namespace")
        if resolution in {"static-resolved", "observed-runtime"}:
            if architecture != "match":
                fail(f"{label} cannot be resolved without architecture=match")
            if soname != "match":
                fail(f"{label} cannot be resolved without soname=match")
            if symbol_abi != "satisfied":
                fail(f"{label} cannot be resolved without symbol_abi=satisfied")
            if namespace != "visible":
                fail(f"{label} cannot be resolved without namespace=visible")
        if edge_type == "elf-dlopen-candidate" and resolution == "static-resolved":
            fail(f"{label} dlopen candidates cannot be promoted to static-resolved without runtime evidence")
    return edge_id, resolution


def validate_platform_contract(row: object, index: int) -> str:
    label = f"target_platform_contracts[{index}]"
    if not isinstance(row, dict):
        fail(f"{label} must be an object")
    for key in ("consumer", "dependency"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            fail(f"{label}.{key} must be non-empty")
    require_hash_list(row.get("target_evidence_sha256"), f"{label}.target_evidence_sha256")

    classification = row.get("target_classification")
    if classification not in {"compatible", "missing", "abi-mismatch", "namespace-invisible", "unknown"}:
        fail(f"{label}.target_classification is invalid")

    if classification == "compatible":
        required = {
            "architecture": "match",
            "soname": "match",
            "symbol_abi": "satisfied",
            "namespace": "visible",
        }
        for key, expected in required.items():
            if row.get(key) != expected:
                fail(f"{label} compatible requires {key}={expected}")
        provider = row.get("target_provider")
        if not isinstance(provider, str) or not provider.strip():
            fail(f"{label} compatible requires target_provider")

    if classification == "missing" and row.get("target_provider"):
        fail(f"{label} missing must not claim target_provider")
    if classification == "abi-mismatch" and row.get("symbol_abi") != "unsatisfied":
        fail(f"{label} abi-mismatch requires symbol_abi=unsatisfied")
    if classification == "namespace-invisible" and row.get("namespace") != "not-visible":
        fail(f"{label} namespace-invisible requires namespace=not-visible")
    return classification


def validate(value: object, max_age_days: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("contract root must be an object")
    if value.get("schema") != 1:
        fail("schema must equal 1")
    generated = parse_time(value.get("generated_at_utc"), max_age_days)

    target = value.get("target")
    if not isinstance(target, dict):
        fail("target must be an object")
    product = target.get("product")
    sdk = target.get("sdk")
    fingerprint = target.get("build_fingerprint_sha256")
    if not isinstance(product, str) or not product.strip():
        fail("target.product must be non-empty")
    if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
        fail("target.sdk must be a positive integer")
    if not isinstance(fingerprint, str) or not HASH_RE.fullmatch(fingerprint):
        fail("target.build_fingerprint_sha256 must be a lowercase SHA-256")

    edges = value.get("edges")
    if not isinstance(edges, list) or not edges:
        fail("edges must be a non-empty array")
    resolutions: dict[str, str] = {}
    for index, row in enumerate(edges):
        edge_id, resolution = validate_edge(row, index)
        if edge_id in resolutions:
            fail(f"duplicate edge_id: {edge_id}")
        resolutions[edge_id] = resolution

    closures = value.get("closures")
    if not isinstance(closures, dict):
        fail("closures must be an object")
    expected_closures = {"static", "declarative", "observed_runtime"}
    if set(closures) != expected_closures:
        fail("closures must contain exactly static, declarative, observed_runtime")

    membership: dict[str, str] = {}
    for name in ("static", "declarative", "observed_runtime"):
        rows = closures[name]
        if not isinstance(rows, list):
            fail(f"closures.{name} must be an array")
        if len(rows) != len(set(rows)):
            fail(f"closures.{name} contains duplicates")
        for edge_id in rows:
            if edge_id not in resolutions:
                fail(f"closures.{name} references unknown edge_id: {edge_id}")
            if edge_id in membership:
                fail(f"edge_id appears in multiple closures: {edge_id}")
            membership[edge_id] = name

    observed_ids = set(closures["observed_runtime"])
    for edge_id in observed_ids:
        if resolutions[edge_id] != "observed-runtime":
            fail(f"observed_runtime closure requires observed-runtime resolution: {edge_id}")

    contracts = value.get("target_platform_contracts")
    if not isinstance(contracts, list):
        fail("target_platform_contracts must be an array")
    counts = {key: 0 for key in ("compatible", "missing", "abi-mismatch", "namespace-invisible", "unknown")}
    for index, row in enumerate(contracts):
        counts[validate_platform_contract(row, index)] += 1

    return {
        "schema": 1,
        "valid": True,
        "generated_at_utc": generated,
        "target_product": product,
        "target_sdk": sdk,
        "edge_count": len(edges),
        "closure_counts": {name: len(closures[name]) for name in closures},
        "target_platform_counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()

    if args.max_age_days < -1:
        parser.error("--max-age-days must be -1 or greater")
    if args.contract.is_symlink() or not args.contract.is_file():
        raise ValueError("contract must be a regular non-symlink file")
    value = json.loads(args.contract.read_text(encoding="utf-8"))
    result = validate(value, args.max_age_days)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_path is not None:
        if args.json_path.is_symlink():
            raise ValueError("JSON output must not be a symlink")
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(2)
