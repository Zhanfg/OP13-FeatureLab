# SPDX-License-Identifier: GPL-3.0-only
"""OP13 FeatureLab local generator, assembler, and semantic auditor."""

from .assembly_policy import AssemblyError, ModuleMetadata
from .assembler import assemble_validation_module
from .audit import AuditError, AuditReport, audit_trees
from .generator import GenerationError, generate_payload
from .propertyplan import PropertyPlanError, build_property_plan, render_property_plan
from .snapshot import SnapshotError, capture_property_snapshot

__all__ = [
    "AssemblyError",
    "AuditError",
    "AuditReport",
    "GenerationError",
    "ModuleMetadata",
    "PropertyPlanError",
    "SnapshotError",
    "assemble_validation_module",
    "audit_trees",
    "build_property_plan",
    "capture_property_snapshot",
    "generate_payload",
    "render_property_plan",
]

__version__ = "0.4.0"
