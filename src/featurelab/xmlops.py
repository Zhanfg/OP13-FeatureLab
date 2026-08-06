# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .selectors import find_matches, find_with_parents
from .util import atomic_write_bytes

KEY_ATTRIBUTES = ("name", "package", "packageName", "id", "key", "component", "activity")


class XmlOperationError(RuntimeError):
    pass


def parse_xml(path: Path) -> tuple[ET.ElementTree, bool]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    try:
        tree = ET.parse(path, parser=parser)
    except ET.ParseError as exc:
        raise XmlOperationError(f"XML parse failed for {path}: {exc}") from exc
    has_declaration = path.read_bytes().lstrip().startswith(b"<?xml")
    return tree, has_declaration


def write_xml(tree: ET.ElementTree, path: Path, *, declaration: bool) -> None:
    ET.indent(tree, space="    ")
    payload = ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=declaration)
    atomic_write_bytes(path, payload + b"\n")


def _element_from_value(value: Any) -> ET.Element:
    if not isinstance(value, dict) or not isinstance(value.get("tag"), str):
        raise XmlOperationError("xml_add requires value={tag, attributes?, text?, children?}")
    element = ET.Element(value["tag"], {str(k): str(v) for k, v in value.get("attributes", {}).items()})
    if value.get("text") is not None:
        element.text = str(value["text"])
    for child in value.get("children", []):
        element.append(_element_from_value(child))
    return element


def apply_xml_operation(tree: ET.ElementTree, operation: dict[str, Any]) -> dict[str, Any]:
    root = tree.getroot()
    operation_type = operation["type"]
    selector = operation["selector"]
    matches = find_matches(root, selector)

    if operation_type == "xml_add":
        if len(matches) != 1:
            raise XmlOperationError(f"xml_add selector must match exactly one parent: {selector!r}, got {len(matches)}")
        element = _element_from_value(operation.get("value"))
        matches[0].append(element)
        return {"matched": 1, "changed": 1}

    if operation_type == "xml_update":
        if not matches:
            raise XmlOperationError(f"xml_update selector did not match: {selector!r}")
        value = operation.get("value")
        if not isinstance(value, dict):
            raise XmlOperationError("xml_update requires an object value")
        changed = 0
        for element in matches:
            for key, item in value.get("attributes", {}).items():
                if element.get(str(key)) != str(item):
                    element.set(str(key), str(item))
                    changed += 1
            if "text" in value and element.text != str(value["text"]):
                element.text = str(value["text"])
                changed += 1
        return {"matched": len(matches), "changed": changed}

    if operation_type == "xml_remove_exact":
        pairs = find_with_parents(root, selector)
        if not pairs:
            raise XmlOperationError(f"xml_remove_exact selector did not match: {selector!r}")
        removed_keys: list[str] = []
        for parent, child in pairs:
            if parent is root:
                key = next((child.get(attr) for attr in KEY_ATTRIBUTES if child.get(attr)), None)
                if key:
                    removed_keys.append(f"{child.tag}:{key}")
            parent.remove(child)
        return {"matched": len(pairs), "changed": len(pairs), "removed_keys": removed_keys}

    if operation_type == "list_append":
        if len(matches) != 1:
            raise XmlOperationError(f"list_append selector must match exactly one element: {selector!r}, got {len(matches)}")
        token = operation.get("value")
        if not isinstance(token, str) or not token.strip():
            raise XmlOperationError("list_append requires a non-empty string value")
        element = matches[0]
        current = (element.text or "").strip()
        normalized = [item.strip() for item in current.replace("\n", ",").replace(";", ",").split(",") if item.strip()]
        if token in normalized:
            return {"matched": 1, "changed": 0}
        normalized.append(token)
        element.text = ",".join(normalized)
        return {"matched": 1, "changed": 1}

    if operation_type == "permission_add":
        if len(matches) != 1:
            raise XmlOperationError(f"permission_add selector must match one package: {selector!r}, got {len(matches)}")
        permission = operation.get("value")
        if isinstance(permission, dict):
            permission = permission.get("name")
        if not isinstance(permission, str) or not permission:
            raise XmlOperationError("permission_add requires a permission name")
        package = matches[0]
        for child in list(package):
            if child.tag == "permission" and child.get("name") == permission:
                return {"matched": 1, "changed": 0}
        package.append(ET.Element("permission", {"name": permission}))
        return {"matched": 1, "changed": 1}

    raise XmlOperationError(f"unsupported XML operation type: {operation_type}")


def clone_tree(tree: ET.ElementTree) -> ET.ElementTree:
    return ET.ElementTree(copy.deepcopy(tree.getroot()))
