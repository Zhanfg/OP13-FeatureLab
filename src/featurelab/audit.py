# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .util import sha256_file
from .xmlops import XmlOperationError, parse_xml

PROTECTED_PATH_PATTERNS = (
    "/data/system/locksettings",
    "/data/system/spblob/",
    "/data/misc/gatekeeper/",
    "/data/vendor/weaver/",
    "/metadata/vold/",
    "/data/unencrypted/",
)

CREDENTIAL_TERMS = re.compile(
    r"locksettings|keyguard|credential|confirmcredential|privacy[_ .-]?password|privacypassword|"
    r"private[_ .-]?safe|app[_ .-]?lock|applock|app[_ .-]?hide|securitycenter|safecenter|"
    r"fingerprint|biometric",
    re.IGNORECASE,
)
CAMERA_BOUNDARY_TERMS = re.compile(
    r"camera|portrait|photograph|live[_ .-]?photo|beauty|lumo|"
    r"face[^\s<>=]{0,40}(?:enroll|detect|unlock|auth)|biometric[^\s<>=]{0,24}face",
    re.IGNORECASE,
)
PERMISSION_FILE_TERMS = re.compile(r"privapp-permissions|permissions", re.IGNORECASE)
KEY_ATTRIBUTES = ("name", "package", "packageName", "id", "key", "component", "activity")
PROJECT_METADATA_FILES = {Path("featurelab-generation.json")}


class AuditError(RuntimeError):
    pass


@dataclass
class Finding:
    severity: str
    code: str
    path: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class AuditReport:
    verdict: str
    baseline_root: str
    generated_root: str
    files_compared: int
    findings: list[Finding]
    permission_additions: dict[str, dict[str, list[str]]]
    manifests: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["findings"] = [asdict(item) for item in self.findings]
        return result


def _serialize_element(element: ET.Element) -> str:
    """Return a formatting-independent semantic representation."""
    def canonical(node: ET.Element) -> object:
        return {
            "tag": node.tag if isinstance(node.tag, str) else "#comment",
            "attributes": sorted(node.attrib.items()),
            "text": (node.text or "").strip(),
            "children": [canonical(child) for child in list(node)],
        }

    return json.dumps(canonical(element), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _semantic_text(element: ET.Element) -> str:
    tag = element.tag if isinstance(element.tag, str) else "#comment"
    parts = [tag]
    for key, value in sorted(element.attrib.items()):
        parts.extend((key, value))
    if element.text:
        parts.append(element.text)
    return " ".join(parts)


def _protected_signatures(root: ET.Element, pattern: re.Pattern[str]) -> list[str]:
    signatures = []
    for element in root.iter():
        if pattern.search(_semantic_text(element)):
            signatures.append(_serialize_element(element))
    return sorted(signatures)


def _permission_map(root: ET.Element) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for element in root.iter():
        package_name = None
        if element.tag in {"privapp-permissions", "permissions", "package"}:
            package_name = element.get("package") or element.get("name")
        if not package_name:
            continue
        for child in list(element):
            if child.tag == "permission" and child.get("name"):
                result[package_name].add(child.get("name", ""))
    return result


def _top_level_keyed_records(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in list(root):
        key = next((child.get(attr) for attr in KEY_ATTRIBUTES if child.get(attr)), None)
        if key:
            result[f"{child.tag}:{key}"] = _serialize_element(child)
    return result


def _iter_relative_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path.relative_to(root)


def _audit_xml(
    relative: Path,
    baseline: Path,
    generated: Path,
    findings: list[Finding],
    additions: dict[str, dict[str, list[str]]],
    allowed_removed_keys: set[str],
) -> None:
    try:
        baseline_tree, _ = parse_xml(baseline)
        generated_tree, _ = parse_xml(generated)
    except XmlOperationError as exc:
        findings.append(Finding("blocker", "XML_PARSE_FAILED", f"/{relative.as_posix()}", str(exc)))
        return

    baseline_root = baseline_tree.getroot()
    generated_root = generated_tree.getroot()
    target = f"/{relative.as_posix()}"

    baseline_credentials = _protected_signatures(baseline_root, CREDENTIAL_TERMS)
    generated_credentials = _protected_signatures(generated_root, CREDENTIAL_TERMS)
    if baseline_credentials != generated_credentials:
        findings.append(
            Finding(
                "blocker",
                "PROTECTED_CREDENTIAL_SEMANTICS_CHANGED",
                target,
                "Credential, Keyguard, privacy-password, fingerprint or security-center semantics changed.",
                {
                    "baseline_count": len(baseline_credentials),
                    "generated_count": len(generated_credentials),
                    "removed": sorted(set(baseline_credentials) - set(generated_credentials))[:50],
                    "added": sorted(set(generated_credentials) - set(baseline_credentials))[:50],
                },
            )
        )

    baseline_camera = _protected_signatures(baseline_root, CAMERA_BOUNDARY_TERMS)
    generated_camera = _protected_signatures(generated_root, CAMERA_BOUNDARY_TERMS)
    if baseline_camera != generated_camera:
        findings.append(
            Finding(
                "blocker",
                "CAMERA_FACE_BIOMETRIC_BOUNDARY_CHANGED",
                target,
                "Camera, face or biometric-adjacent semantics changed.",
                {
                    "baseline_count": len(baseline_camera),
                    "generated_count": len(generated_camera),
                    "removed": sorted(set(baseline_camera) - set(generated_camera))[:50],
                    "added": sorted(set(generated_camera) - set(baseline_camera))[:50],
                },
            )
        )

    if PERMISSION_FILE_TERMS.search(relative.name):
        baseline_permissions = _permission_map(baseline_root)
        generated_permissions = _permission_map(generated_root)
        for package, original in baseline_permissions.items():
            removed = sorted(original - generated_permissions.get(package, set()))
            if removed:
                findings.append(
                    Finding(
                        "blocker",
                        "PRIVILEGED_PERMISSION_REMOVED",
                        target,
                        f"Original permissions were removed from {package}.",
                        {"package": package, "removed": removed},
                    )
                )
            added = sorted(generated_permissions.get(package, set()) - original)
            if added:
                additions.setdefault(target, {})[package] = added
        for package, permissions in generated_permissions.items():
            if package not in baseline_permissions and permissions:
                additions.setdefault(target, {})[package] = sorted(permissions)

    baseline_records = _top_level_keyed_records(baseline_root)
    generated_records = _top_level_keyed_records(generated_root)
    removed_keys = sorted((set(baseline_records) - set(generated_records)) - allowed_removed_keys)
    if removed_keys:
        findings.append(
            Finding(
                "blocker",
                "TOP_LEVEL_POLICY_RECORDS_REMOVED",
                target,
                "Generated XML removed keyed top-level records from the baseline.",
                {"count": len(removed_keys), "keys": removed_keys[:100]},
            )
        )


def audit_trees(
    baseline_root: Path,
    generated_root: Path,
    *,
    allowed_top_level_removals: dict[str, set[str]] | None = None,
) -> AuditReport:
    baseline_root = baseline_root.resolve()
    generated_root = generated_root.resolve()
    if not baseline_root.is_dir() or not generated_root.is_dir():
        raise AuditError("baseline and generated roots must both be directories")

    findings: list[Finding] = []
    allowed_top_level_removals = allowed_top_level_removals or {}
    permission_additions: dict[str, dict[str, list[str]]] = {}
    baseline_files = set(_iter_relative_files(baseline_root))
    generated_files = set(_iter_relative_files(generated_root))

    for relative in sorted((generated_files - baseline_files) - PROJECT_METADATA_FILES):
        findings.append(
            Finding(
                "blocker",
                "GENERATED_FILE_WITHOUT_BASELINE",
                f"/{relative.as_posix()}",
                "Generated payload contains a file with no local baseline counterpart.",
            )
        )

    manifests = {"baseline": {}, "generated": {}}
    compared = 0
    for relative in sorted(baseline_files | generated_files):
        baseline = baseline_root / relative
        generated = generated_root / relative
        if baseline.is_file():
            manifests["baseline"][f"/{relative.as_posix()}"] = sha256_file(baseline)
        if generated.is_file():
            manifests["generated"][f"/{relative.as_posix()}"] = sha256_file(generated)

        absolute = f"/{relative.as_posix()}"
        if generated.is_file() and any(absolute.startswith(prefix) for prefix in PROTECTED_PATH_PATTERNS):
            findings.append(Finding("blocker", "PROTECTED_PATH_PRESENT", absolute, "Protected credential path is present."))

        if not baseline.is_file() or not generated.is_file():
            continue
        compared += 1
        if relative.suffix.lower() == ".xml":
            _audit_xml(
                relative,
                baseline,
                generated,
                findings,
                permission_additions,
                allowed_top_level_removals.get(f"/{relative.as_posix()}", set()),
            )
        elif relative.suffix.lower() == ".prop":
            _audit_property_file(relative, generated, findings)

    verdict = "PASS" if not any(item.severity == "blocker" for item in findings) else "FAIL"
    return AuditReport(
        verdict=verdict,
        baseline_root=str(baseline_root),
        generated_root=str(generated_root),
        files_compared=compared,
        findings=findings,
        permission_additions=permission_additions,
        manifests=manifests,
    )


def _parse_properties(path: Path) -> tuple[dict[str, str], list[str], list[str]]:
    values: dict[str, str] = {}
    duplicates: list[str] = []
    malformed: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            malformed.append(f"{line_number}:{raw}")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            malformed.append(f"{line_number}:{raw}")
            continue
        if key in values:
            duplicates.append(key)
        values[key] = value
    return values, duplicates, malformed


def _audit_property_file(relative: Path, generated: Path, findings: list[Finding]) -> None:
    target = f"/{relative.as_posix()}"
    _, duplicates, malformed = _parse_properties(generated)
    if duplicates:
        findings.append(Finding("blocker", "DUPLICATE_PROPERTY_KEYS", target, "Duplicate property keys found.", {"keys": duplicates}))
    if malformed:
        findings.append(Finding("blocker", "MALFORMED_PROPERTY_LINES", target, "Malformed property lines found.", {"lines": malformed}))


def write_report(report: AuditReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
