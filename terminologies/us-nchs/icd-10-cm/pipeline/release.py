"""Read the FY27 CMS ICD-10-CM Tabular XML and companion order file.

FY27 separates the two structured inputs: the `table-and-index` ZIP supplies the authoritative
Tabular XML (chapters, sections, explicit diagnosis nesting, and extension definitions), while the
`code-descriptions` ZIP supplies `icd10cm-order-2027.txt` (the full concrete code list, order number,
submission-valid flag, short description, and long description). The XML does not enumerate every
seventh-character extension code, so those codes keep the longest explicit XML-code prefix as parent.

Sections are direct XML children of chapters. A narrow, reviewed exception adds a structural parent
between sibling sections when the candidate parent has no direct diagnosis and its declared range
contains the child range. `sectionIndex` supplies the authoritative `first`/`last` bounds when it
covers a section; the section id is the documented fallback for the few sections absent from that
index. This creates navigable hierarchy for umbrella sections such as `V00-X58` and `V00-V99`.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

TABULAR_RE = re.compile(r"icd10cm-tabular_-2027\.xml$", re.IGNORECASE)
ORDER_RE = re.compile(r"icd10cm-order-2027\.txt$", re.IGNORECASE)
RANGE_RE = re.compile(r"\(([^()]+)\)\s*$")
SECTION_RANGE_RE = re.compile(r"^([A-Z][A-Z0-9.]*)-([A-Z][A-Z0-9.]*)$")


@dataclass(frozen=True)
class Node:
    code: str
    title: str
    parent: str | None
    kind: str  # chapter, section, diag
    order: int


@dataclass(frozen=True)
class Code:
    code: str
    order_number: int
    valid_for_submission: bool
    short_description: str
    long_description: str
    parent: str


@dataclass
class Release:
    version: str
    tabular_member: str
    order_member: str
    nodes: dict[str, Node] = field(default_factory=dict)
    codes: dict[str, Code] = field(default_factory=dict)
    node_order: list[str] = field(default_factory=list)
    code_order: list[str] = field(default_factory=list)


def dotted(code: str) -> str:
    return f"{code[:3]}.{code[3:]}" if len(code) > 3 else code


def _member(archive: zipfile.ZipFile, pattern: re.Pattern[str], path: Path) -> str:
    matches = [name for name in archive.namelist() if pattern.search(Path(name).name)]
    if len(matches) != 1:
        raise ValueError(f"{path}: expected exactly one member matching {pattern.pattern!r}, found {matches!r}")
    return matches[0]


def _chapter_code(title: str, path: Path) -> str:
    match = RANGE_RE.search(title or "")
    if not match:
        raise ValueError(f"{path}: chapter description has no terminal range identifier: {title!r}")
    return match.group(1)


def _add_node(release: Release, node: Node) -> None:
    if node.code in release.nodes:
        raise ValueError(f"duplicate XML concept id {node.code!r}")
    release.nodes[node.code] = node
    release.node_order.append(node.code)


def _section_range(section_id: str, indexed_ranges: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """Return `sectionIndex` endpoints, or fall back to the range encoded in the section id."""
    if section_id in indexed_ranges:
        return indexed_ranges[section_id]
    match = SECTION_RANGE_RE.fullmatch(section_id)
    if not match:
        return None
    return match.group(1).replace(".", ""), match.group(2).replace(".", "")


def _contains_section_range(parent_id: str, child_id: str, indexed_ranges: dict[str, tuple[str, str]]) -> bool:
    """True when a strict parent range contains the entire child range."""
    parent = _section_range(parent_id, indexed_ranges)
    child = _section_range(child_id, indexed_ranges)
    return bool(parent and child and parent_id != child_id and parent[0] <= child[0] and child[1] <= parent[1])


def _section_parents(chapter_code: str, chapter: ET.Element, sections: list[ET.Element]) -> dict[str, str]:
    """Derive section nesting from `sectionIndex` bounds, with an id-range fallback."""
    index = chapter.find("sectionIndex")
    indexed_ranges = {
        (reference.get("id") or "").strip(): ((reference.get("first") or "").replace(".", ""), (reference.get("last") or "").replace(".", ""))
        for reference in (index.findall("sectionRef") if index is not None else [])
        if reference.get("id") and reference.get("first") and reference.get("last")
    }
    emitted: list[ET.Element] = []
    for section in sections:
        section_id = (section.get("id") or "").strip()
        direct_diagnoses = section.findall("diag")
        is_code_wrapper = any((diagnosis.findtext("name") or "").strip() == section_id for diagnosis in direct_diagnoses)
        if is_code_wrapper:
            continue
        emitted.append(section)

    parents: dict[str, str] = {}
    for section in emitted:
        section_id = (section.get("id") or "").strip()
        candidates = [
            (candidate.get("id") or "").strip()
            for candidate in emitted
            if not candidate.findall("diag")
            and _contains_section_range((candidate.get("id") or "").strip(), section_id, indexed_ranges)
        ]
        narrowest = [
            candidate for candidate in candidates
            if not any(other != candidate and _contains_section_range(candidate, other, indexed_ranges) for other in candidates)
        ]
        if len(narrowest) > 1:
            raise ValueError(
                f"ambiguous editorial section parents for {section_id!r} in chapter {chapter_code!r}: {narrowest!r}"
            )
        parents[section_id] = narrowest[0] if narrowest else chapter_code
    return parents


def _read_xml(path: Path, archive: zipfile.ZipFile, member: str) -> Release:
    root = ET.fromstring(archive.read(member))
    if root.tag != "ICD10CM.tabular":
        raise ValueError(f"{path}: expected ICD10CM.tabular root, found {root.tag!r}")
    version = (root.findtext("version") or "").strip()
    if version != "2027":
        raise ValueError(f"{path}: expected XML version 2027, found {version!r}")
    release = Release(version=version, tabular_member=member, order_member="")
    position = 0

    def visit_diag(element: ET.Element, parent: str) -> None:
        nonlocal position
        code = (element.findtext("name") or "").strip()
        title = (element.findtext("desc") or "").strip()
        if not code or not title:
            raise ValueError(f"{path}: diagnosis element under {parent!r} has no code/title")
        position += 1
        _add_node(release, Node(code=code, title=title, parent=parent, kind="diag", order=position))
        for child in element.findall("diag"):
            visit_diag(child, code)

    for chapter in root.findall("chapter"):
        chapter_title = (chapter.findtext("desc") or "").strip()
        chapter_code = _chapter_code(chapter_title, path)
        position += 1
        _add_node(release, Node(chapter_code, chapter_title, None, "chapter", position))
        sections = chapter.findall("section")
        section_parents = _section_parents(chapter_code, chapter, sections)
        section_records: list[tuple[ET.Element, str, str, list[ET.Element], bool]] = []
        for section in sections:
            section_code = (section.get("id") or "").strip()
            section_title = (section.findtext("desc") or "").strip()
            if not section_code or not section_title:
                raise ValueError(f"{path}: section under {chapter_code!r} has no id/title")
            direct_diagnoses = section.findall("diag")
            # Some CMS sections are a wrapper whose id is the sole diagnosis code (e.g. section B10
            # contains diag B10). OCL cannot model both as different concepts with the same mnemonic;
            # retain the diagnosis and attach it directly to the chapter, matching the existing staging tree.
            section_is_code = any((diagnosis.findtext("name") or "").strip() == section_code for diagnosis in direct_diagnoses)
            section_records.append((section, section_code, section_title, direct_diagnoses, section_is_code))

        depth_cache: dict[str, int] = {}

        def section_depth(section_code: str) -> int:
            if section_code in depth_cache:
                return depth_cache[section_code]
            parent = section_parents[section_code]
            depth_cache[section_code] = 0 if parent == chapter_code else section_depth(parent) + 1
            return depth_cache[section_code]

        for _, section_code, section_title, _, section_is_code in sorted(
            section_records, key=lambda row: (section_depth(row[1]) if not row[4] else 0, row[1])
        ):
            if not section_is_code:
                position += 1
                _add_node(release, Node(section_code, section_title, section_parents[section_code], "section", position))

        for _, section_code, _, direct_diagnoses, section_is_code in section_records:
            diagnosis_parent = chapter_code if section_is_code else section_code
            for diagnosis in direct_diagnoses:
                visit_diag(diagnosis, diagnosis_parent)
    return release


def _read_order(path: Path, archive: zipfile.ZipFile, member: str, release: Release) -> None:
    codes_seen: set[str] = set()
    for number, raw in enumerate(archive.read(member).decode("utf-8-sig").splitlines(), start=1):
        if len(raw) < 77:
            raise ValueError(f"{path}: order row {number} is shorter than the fixed-width layout")
        order_text, raw_code, flag = raw[:5], raw[6:13].strip(), raw[14:15]
        short, long = raw[16:76].rstrip(), raw[77:].strip()
        if not order_text.isdigit() or not raw_code or flag not in {"0", "1"} or not long:
            raise ValueError(f"{path}: malformed order row {number}")
        code = dotted(raw_code)
        if code in codes_seen:
            raise ValueError(f"{path}: duplicate order code {code!r}")
        codes_seen.add(code)
        if code in release.nodes:
            parent = release.nodes[code].parent
        else:
            parent = next((candidate for candidate in (code[:end] for end in range(len(code) - 1, 0, -1)) if candidate in release.nodes), None)
        if not parent:
            raise ValueError(f"{path}: order code {code!r} has no explicit XML parent or resolvable explicit stem")
        release.codes[code] = Code(code, int(order_text), flag == "1", short, long, parent)
        release.code_order.append(code)
    missing_explicit = sorted(code for code, node in release.nodes.items() if node.kind == "diag" and code not in release.codes)
    if missing_explicit:
        raise ValueError(f"{path}: {len(missing_explicit)} explicit XML diagnosis code(s) are absent from the order file, e.g. {missing_explicit[:5]}")


def read(tabular_zip: Path, order_zip: Path | None = None) -> Release:
    tabular_zip = Path(tabular_zip)
    order_zip = Path(order_zip) if order_zip else tabular_zip
    if not tabular_zip.is_file() or not order_zip.is_file():
        raise FileNotFoundError(f"ICD-10-CM input ZIP missing: tabular={tabular_zip}, order={order_zip}")
    with zipfile.ZipFile(tabular_zip) as tabular_archive:
        tabular_member = _member(tabular_archive, TABULAR_RE, tabular_zip)
        release = _read_xml(tabular_zip, tabular_archive, tabular_member)
    with zipfile.ZipFile(order_zip) as order_archive:
        order_member = _member(order_archive, ORDER_RE, order_zip)
        release.order_member = order_member
        _read_order(order_zip, order_archive, order_member, release)
    return release
