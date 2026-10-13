"""Shared, deliberately narrow XML reading for the ClaML adapters.

ElementTree does not resolve external DTDs, so an external ``<!DOCTYPE … SYSTEM …>`` (which the
French ClaML carries) is harmless and is accepted. An internal DTD subset or an entity
declaration is refused: entity expansion is never needed to read a label, and allowing it invites
entity-expansion attacks.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

INTERNAL_SUBSET = re.compile(rb"<!\s*DOCTYPE[^>]*\[")


def parse_claml(path: Path, root_tag: str = "ClaML") -> ET.Element:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"ClaML file not found: {path}")
    payload = path.read_bytes()
    if b"<!ENTITY" in payload or INTERNAL_SUBSET.search(payload):
        raise ValueError(
            f"{path}: refusing to parse a ClaML file with an internal DTD subset or entity "
            "declarations; entity expansion is not needed to read labels"
        )
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError(f"{path}: not well-formed XML: {error}") from None
    if root.tag != root_tag:
        raise ValueError(f"{path}: expected a {root_tag} root element, found {root.tag!r}")
    return root


def preferred_label_text(class_element: ET.Element) -> str:
    """The first preferred rubric's label, using the label's own text only."""
    for rubric in class_element.findall("Rubric"):
        if rubric.get("kind") != "preferred":
            continue
        for label in rubric.findall("Label"):
            return (label.text or "").strip()
    return ""
