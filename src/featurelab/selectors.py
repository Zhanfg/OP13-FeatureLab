# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_SEGMENT = re.compile(
    r"^(?P<tag>[A-Za-z_][A-Za-z0-9_.:-]*|\*)"
    r"(?:\[(?P<attr>[A-Za-z_][A-Za-z0-9_.:-]*)=(?P<value>[^\]]+)\])?$"
)


class SelectorError(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    tag: str
    attribute: str | None = None
    value: str | None = None

    def matches(self, element: ET.Element) -> bool:
        if self.tag != "*" and element.tag != self.tag:
            return False
        if self.attribute is None:
            return True
        return element.get(self.attribute) == self.value


def parse_selector(selector: str) -> list[Segment]:
    if not selector or selector.startswith("/") or "//" in selector:
        raise SelectorError(f"unsupported selector: {selector!r}")
    result: list[Segment] = []
    for raw in selector.split("/"):
        match = _SEGMENT.fullmatch(raw.strip())
        if not match:
            raise SelectorError(f"invalid selector segment: {raw!r}")
        value = match.group("value")
        if value is not None:
            value = value.strip().strip('"\'')
        result.append(Segment(match.group("tag"), match.group("attr"), value))
    return result


def find_matches(root: ET.Element, selector: str) -> list[ET.Element]:
    segments = parse_selector(selector)
    current = [root]
    first = segments[0]

    if first.matches(root):
        current = [root]
        segments = segments[1:]
    else:
        current = [child for child in list(root) if first.matches(child)]
        segments = segments[1:]

    for segment in segments:
        next_level: list[ET.Element] = []
        for parent in current:
            next_level.extend(child for child in list(parent) if segment.matches(child))
        current = next_level
    return current


def find_with_parents(root: ET.Element, selector: str) -> list[tuple[ET.Element, ET.Element]]:
    targets = set(map(id, find_matches(root, selector)))
    result: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if id(child) in targets:
                result.append((parent, child))
    return result
