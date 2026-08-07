# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import AuditError, audit_trees, write_report
from .generator import GenerationError, generate_payload
from .snapshot import SnapshotError, capture_property_snapshot


def _selected(value: str | None) -> set[str] | None:
    if value is None:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="op13-featurelab")
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate = subcommands.add_parser("generate", help="generate a local payload from a device baseline")
    generate.add_argument("--baseline", required=True, type=Path)
    generate.add_argument("--catalog", required=True, type=Path)
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--report", required=True, type=Path)
    generate.add_argument("--features", help="comma-separated feature IDs; omit to use default_enabled entries")
    generate.add_argument("--property-snapshot", type=Path, help="local allowlisted property snapshot JSON")

    snapshot = subcommands.add_parser(
        "snapshot-properties",
        help="create a local allowlisted property snapshot from a getprop dump",
    )
    snapshot.add_argument("--catalog", required=True, type=Path)
    snapshot.add_argument("--getprop-dump", required=True, type=Path)
    snapshot.add_argument("--output", required=True, type=Path)
    snapshot.add_argument("--features", help="comma-separated feature IDs; omit to use default_enabled entries")

    audit = subcommands.add_parser("audit", help="compare a baseline tree with a generated tree")
    audit.add_argument("--baseline", required=True, type=Path)
    audit.add_argument("--generated", required=True, type=Path)
    audit.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            manifest = generate_payload(
                args.baseline,
                args.catalog,
                args.output,
                args.report,
                selected_features=_selected(args.features),
                property_snapshot_path=args.property_snapshot,
            )
            print(json.dumps({"ok": True, "selected_features": manifest["selected_features"]}, ensure_ascii=False))
            return 0
        if args.command == "snapshot-properties":
            metadata = capture_property_snapshot(
                args.catalog,
                args.getprop_dump,
                args.output,
                selected_features=_selected(args.features),
            )
            print(json.dumps({"ok": True, **metadata}, ensure_ascii=False))
            return 0

        report = audit_trees(args.baseline, args.generated)
        write_report(report, args.report)
        print(
            json.dumps(
                {"ok": report.verdict == "PASS", "verdict": report.verdict, "findings": len(report.findings)}
            )
        )
        return 0 if report.verdict == "PASS" else 2
    except (GenerationError, SnapshotError, AuditError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
