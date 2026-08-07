# SPDX-License-Identifier: GPL-3.0-only
"""OP13 FeatureLab local generator, assembler, and semantic auditor."""

from .assembly_policy import AssemblyError, ModuleMetadata
from .assembler import assemble_validation_module
from .audit import AuditError, AuditReport, audit_trees
from .compatibility import CompatibilityBuildError, build_compatibility_profile
from .generator import GenerationError, generate_payload
from .preflight import PreflightAnalysisError, PreflightAnalysisResult, analyze_preflight_archive
from .propertyplan import PropertyPlanError, build_property_plan, render_property_plan
from .snapshot import SnapshotError, capture_property_snapshot

__all__ = [
    "AssemblyError",
    "CompatibilityBuildError",
    "AuditError",
    "AuditReport",
    "GenerationError",
    "ModuleMetadata",
    "PreflightAnalysisError",
    "PreflightAnalysisResult",
    "PropertyPlanError",
    "SnapshotError",
    "analyze_preflight_archive",
    "assemble_validation_module",
    "audit_trees",
    "build_compatibility_profile",
    "build_property_plan",
    "capture_property_snapshot",
    "generate_payload",
    "render_property_plan",
]

__version__ = "0.6.0"
