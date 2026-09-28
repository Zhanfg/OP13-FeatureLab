#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fail when a provider/reference tree that should be inert still mutates runtime state."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

TEXT_LIMIT = 2 * 1024 * 1024
CONTROL_COMMANDS = {
    "pkill": "process-control", "killall": "process-control", "kill": "process-control",
    "umount": "mount-mutation", "resetprop": "property-mutation", "setprop": "property-mutation",
    "setenforce": "selinux-mutation", "reboot": "reboot", "start": "init-service-control",
    "stop": "init-service-control", "nsenter": "namespace-mutation",
    "magiskpolicy": "live-policy-mutation", "supolicy": "live-policy-mutation",
}
SHARED_PREFIXES = ("/data/", "/system/", "/system_ext/", "/vendor/", "/odm/", "/product/", "/my_product/")


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    line: int
    excerpt: str


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def tokenized_segments(line: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for segment in re.split(r"(?:&&|\|\||;|\|)", line):
        stripped = segment.strip()
        if not stripped:
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        while tokens and (
            tokens[0] in {"if", "then", "elif", "else", "do", "done", "while", "until", "!", "{"}
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])
        ):
            tokens.pop(0)
        if tokens and tokens[0] in {"command", "exec"}:
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                tokens.pop(0)
        if tokens:
            rows.append(tokens)
    return rows


def shell_findings(path: Path, repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = relative(path, repo_root)
    for line_no, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for tokens in tokenized_segments(raw):
            command = Path(tokens[0]).name
            if command in CONTROL_COMMANDS:
                findings.append(Finding(CONTROL_COMMANDS[command], rel, line_no, stripped[:300]))
                continue
            if command == "mount" and len(tokens) > 1:
                findings.append(Finding("mount-mutation", rel, line_no, stripped[:300]))
                continue
            if command == "service" and len(tokens) > 1 and tokens[1] != "list":
                findings.append(Finding("binder-service-control", rel, line_no, stripped[:300]))
                continue
            if command == "rm":
                recursive_or_force = any(token.startswith("-") and ("r" in token or "f" in token) for token in tokens[1:])
                targets = [token for token in tokens[1:] if not token.startswith("-")]
                if recursive_or_force and any(target.startswith(SHARED_PREFIXES) for target in targets):
                    findings.append(Finding("shared-data-deletion", rel, line_no, stripped[:300]))
                    continue
            if command in {"chmod", "chown", "chcon", "restorecon"}:
                targets = [token for token in tokens[1:] if not token.startswith("-")]
                if any(target.startswith(SHARED_PREFIXES) for target in targets):
                    findings.append(Finding("system-path-metadata-mutation", rel, line_no, stripped[:300]))
                    continue
            if raw.rstrip().endswith("&"):
                executable = tokens[0]
                if executable.startswith(("/vendor/", "/odm/", "/system/vendor/")):
                    findings.append(Finding("direct-vendor-binary-launch", rel, line_no, stripped[:300]))
    return findings


def scan(root: Path, repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not root.is_dir():
        return [Finding("missing-root", relative(root, repo_root), 0, "")]
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > TEXT_LIMIT:
            continue
        rel_provider = path.relative_to(root).as_posix()
        if path.suffix == ".sh":
            findings.extend(shell_findings(path, repo_root))
        if "/etc/init/" in f"/{rel_provider}" and path.suffix == ".rc":
            findings.append(Finding("active-init-overlay", relative(path, repo_root), 1, rel_provider))
        if "/etc/vintf/" in f"/{rel_provider}" and path.suffix == ".xml":
            findings.append(Finding("active-vintf-overlay", relative(path, repo_root), 1, rel_provider))
        if path.name == "system.prop":
            active = [(n, line.strip()) for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if line.strip() and not line.lstrip().startswith("#") and "=" in line]
            if active:
                findings.append(Finding("active-property-override", relative(path, repo_root), active[0][0], active[0][1][:300]))
        if path.name == "sepolicy.rule":
            active = [(n, line.strip()) for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if line.strip() and not line.lstrip().startswith("#")]
            if active:
                findings.append(Finding("active-selinux-rule", relative(path, repo_root), active[0][0], active[0][1][:300]))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("roots", nargs="+")
    args = parser.parse_args()

    if args.repo.is_symlink():
        raise ValueError("repository root must not be a symlink")
    repo_root = args.repo.resolve()
    if not repo_root.is_dir():
        raise ValueError("repository root must be a directory")

    findings: list[Finding] = []
    normalized_roots: list[str] = []
    for value in args.roots:
        root = (repo_root / value).resolve()
        try:
            root.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"scan root escapes repository: {value}") from exc
        normalized_roots.append(value)
        findings.extend(scan(root, repo_root))

    report = {"schema": 1, "inert": not findings, "roots": normalized_roots, "finding_count": len(findings), "findings": [asdict(item) for item in findings]}
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_path is not None:
        if args.json_path.is_symlink():
            raise ValueError("JSON output must not be a symlink")
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    for finding in findings:
        print(f"[FAIL] {finding.category}: {finding.path}:{finding.line}: {finding.excerpt}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(2)
