#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Audit media/provider payload roots for conflicting target paths."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PARTITIONS = ("system", "vendor", "odm", "product", "system_ext", "my_product")


def collect(root: Path) -> set[str]:
    paths: set[str] = set()
    for partition in PARTITIONS:
        base = root / partition
        if not base.exists():
            continue
        for item in base.rglob("*"):
            if item.is_file():
                paths.add(item.relative_to(root).as_posix())
    return paths


def parse_provider(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("provider must use LABEL=PATH")
    label, raw = value.split("=", 1)
    if not label or not raw:
        raise argparse.ArgumentTypeError("provider must use non-empty LABEL=PATH")
    return label, Path(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", nargs="+", type=parse_provider)
    args = parser.parse_args()

    if len(args.provider) < 2:
        parser.error("at least two providers are required")

    inventories: dict[str, set[str]] = {}
    for label, root in args.provider:
        if label in inventories:
            parser.error(f"duplicate provider label: {label}")
        if not root.is_dir():
            parser.error(f"provider root is not a directory: {root}")
        inventories[label] = collect(root)

    owners: dict[str, list[str]] = {}
    for label, paths in inventories.items():
        for path in paths:
            owners.setdefault(path, []).append(label)

    conflicts = {path: labels for path, labels in owners.items() if len(labels) > 1}
    for path in sorted(conflicts):
        print(f"CONFLICT\t{path}\t{','.join(sorted(conflicts[path]))}")

    if conflicts:
        print(f"FAIL\tconflicts\t{len(conflicts)}")
        return 1

    print("PASS\tconflicts\t0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
