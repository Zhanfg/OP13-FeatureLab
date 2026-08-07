# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assembly_policy import AssemblyError, ModuleMetadata
from .assembler import assemble_validation_module
from .audit import AuditError, audit_trees, write_report
from .compatibility import CompatibilityBuildError, build_compatibility_profile
from .generator import GenerationError, generate_payload
from .preflight import PreflightAnalysisError, analyze_preflight_archive
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

    assemble = subcommands.add_parser(
        "assemble-module",
        help="assemble a local validation-only KernelSU module from audited generated output",
    )
    assemble.add_argument("--generated", required=True, type=Path)
    assemble.add_argument("--compatibility-profile", required=True, type=Path)
    assemble.add_argument("--source-root", required=True, type=Path)
    assemble.add_argument("--output", required=True, type=Path)
    assemble.add_argument("--zip", dest="zip_path", type=Path)
    assemble.add_argument("--acknowledge-test-only", action="store_true")
    assemble.add_argument("--module-id", default="op13.featurelab.validation")
    assemble.add_argument("--module-name", default="OP13 FeatureLab Validation")
    assemble.add_argument("--module-version", default="0.1.0-validation")
    assemble.add_argument("--module-version-code", default=1, type=int)
    assemble.add_argument("--author", default="Axymorrsen")
    assemble.add_argument(
        "--description",
        default="Local PJZ110 validation package; not approved for public flashing",
    )

    compatibility = subcommands.add_parser(
        "build-compatibility-profile",
        help="build a private validation profile from a generation manifest and getprop dump",
    )
    compatibility.add_argument("--generation-manifest", required=True, type=Path)
    compatibility.add_argument("--getprop-dump", required=True, type=Path)
    compatibility.add_argument("--output", required=True, type=Path)
    compatibility.add_argument("--minimum-ksu-version-code", required=True, type=int)
    compatibility.add_argument("--minimum-ksu-kernel-version-code", required=True, type=int)
    compatibility.add_argument("--expected-device", default="PJZ110")
    compatibility.add_argument("--expected-sdk", default="36")
    compatibility.add_argument("--expected-oplus-rom-prefix", default="V16.1")

    preflight = subcommands.add_parser(
        "analyze-preflight",
        help="verify and classify a private read-only device preflight archive",
    )
    preflight.add_argument("--archive", required=True, type=Path)
    preflight.add_argument("--sha256-sidecar", required=True, type=Path)
    preflight.add_argument("--output", required=True, type=Path)

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
        if args.command == "assemble-module":
            result = assemble_validation_module(
                args.generated,
                args.compatibility_profile,
                args.source_root,
                args.output,
                metadata=ModuleMetadata(
                    module_id=args.module_id,
                    name=args.module_name,
                    version=args.module_version,
                    version_code=args.module_version_code,
                    author=args.author,
                    description=args.description,
                ),
                zip_path=args.zip_path,
                acknowledge_test_only=args.acknowledge_test_only,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "build-compatibility-profile":
            result = build_compatibility_profile(
                args.generation_manifest,
                args.getprop_dump,
                args.output,
                minimum_ksu_version_code=args.minimum_ksu_version_code,
                minimum_ksu_kernel_version_code=args.minimum_ksu_kernel_version_code,
                expected_device=args.expected_device,
                expected_sdk=args.expected_sdk,
                expected_oplus_rom_prefix=args.expected_oplus_rom_prefix,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "analyze-preflight":
            result = analyze_preflight_archive(args.archive, args.sha256_sidecar, args.output)
            print(json.dumps(result.as_dict(), ensure_ascii=False))
            return result.exit_code

        report = audit_trees(args.baseline, args.generated)
        write_report(report, args.report)
        print(
            json.dumps(
                {"ok": report.verdict == "PASS", "verdict": report.verdict, "findings": len(report.findings)}
            )
        )
        return 0 if report.verdict == "PASS" else 2
    except (
        GenerationError,
        SnapshotError,
        AssemblyError,
        CompatibilityBuildError,
        PreflightAnalysisError,
        AuditError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
