#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate provider-neutral MediaCodec PCM evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MIME_RE = re.compile(r"^audio/[A-Za-z0-9.+_-]+$")


def fail(message: str) -> None:
    raise ValueError(message)


def require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        fail(f"{label} must be a lowercase SHA-256")
    return value


def require_positive_int(row: dict[str, Any], key: str, label: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        fail(f"{label}.{key} must be a positive integer")
    return value


def parse_time(value: object, max_age_days: int) -> dt.datetime:
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
        fail(f"evidence is older than {max_age_days} days")
    return parsed


def validate(value: object, required_mimes: list[str], max_age_days: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("report root must be an object")
    allowed_root = {"schema", "generated_at_utc", "device", "candidate_manifest_sha256", "decoders"}
    extra_root = sorted(set(value) - allowed_root)
    if extra_root:
        fail("unknown root fields: " + ", ".join(extra_root))
    if value.get("schema") != 1:
        fail("schema must equal 1")
    generated = parse_time(value.get("generated_at_utc"), max_age_days)

    device = value.get("device")
    if not isinstance(device, dict):
        fail("device must be an object")
    if set(device) != {"product", "sdk", "build_fingerprint_sha256"}:
        fail("device fields must be product, sdk, build_fingerprint_sha256")
    product = device.get("product")
    if not isinstance(product, str) or not product.strip():
        fail("device.product must be non-empty")
    sdk = device.get("sdk")
    if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
        fail("device.sdk must be a positive integer")
    require_hash(device.get("build_fingerprint_sha256"), "device.build_fingerprint_sha256")
    manifest_hash = require_hash(value.get("candidate_manifest_sha256"), "candidate_manifest_sha256")

    rows = value.get("decoders")
    if not isinstance(rows, list) or not rows:
        fail("decoders must be a non-empty array")

    seen: set[str] = set()
    components: dict[str, str] = {}
    for index, row in enumerate(rows):
        label = f"decoders[{index}]"
        if not isinstance(row, dict):
            fail(f"{label} must be an object")
        required = {"mime", "component", "decoder_discovered", "create_ok", "output_mime", "pcm_bytes", "pcm_frames", "input_sha256", "pcm_sha256"}
        optional = {"duration_ms", "sample_rate", "channel_count"}
        missing = sorted(required - set(row))
        extra = sorted(set(row) - required - optional)
        if missing:
            fail(f"{label} missing fields: " + ", ".join(missing))
        if extra:
            fail(f"{label} unknown fields: " + ", ".join(extra))

        mime = row.get("mime")
        if not isinstance(mime, str) or not MIME_RE.fullmatch(mime):
            fail(f"{label}.mime is invalid")
        if mime in seen:
            fail(f"duplicate MIME evidence: {mime}")
        seen.add(mime)

        component = row.get("component")
        if not isinstance(component, str) or not component.strip():
            fail(f"{label}.component must be non-empty")
        if row.get("decoder_discovered") is not True:
            fail(f"{label}.decoder_discovered must be true")
        if row.get("create_ok") is not True:
            fail(f"{label}.create_ok must be true")
        if row.get("output_mime") != "audio/raw":
            fail(f"{label}.output_mime must equal audio/raw")
        require_positive_int(row, "pcm_bytes", label)
        require_positive_int(row, "pcm_frames", label)
        for key in optional:
            if key in row:
                require_positive_int(row, key, label)
        require_hash(row.get("input_sha256"), f"{label}.input_sha256")
        require_hash(row.get("pcm_sha256"), f"{label}.pcm_sha256")
        components[mime] = component

    normalized_required: list[str] = []
    for mime in required_mimes:
        if not MIME_RE.fullmatch(mime):
            fail(f"invalid required MIME: {mime}")
        if mime not in normalized_required:
            normalized_required.append(mime)
    missing_required = [mime for mime in normalized_required if mime not in seen]
    if missing_required:
        fail("missing required MIME evidence: " + ", ".join(missing_required))

    return {
        "schema": 1,
        "valid": True,
        "generated_at_utc": generated.isoformat().replace("+00:00", "Z"),
        "device_product": product,
        "device_sdk": sdk,
        "candidate_manifest_sha256": manifest_hash,
        "decoder_count": len(rows),
        "components": dict(sorted(components.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--require-mime", action="append", default=[])
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()

    if args.max_age_days < -1:
        parser.error("--max-age-days must be -1 or greater")
    if args.report.is_symlink() or not args.report.is_file():
        raise ValueError("report must be a regular non-symlink file")
    value = json.loads(args.report.read_text(encoding="utf-8"))
    result = validate(value, args.require_mime, args.max_age_days)
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
