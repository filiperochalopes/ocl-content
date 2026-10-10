"""Reader for the WHO ICD-11 MMS *Simple Tabulation* release.

The release ships the same table as ``.xlsx`` and as a tab-separated ``.txt``; this reader uses the
``.txt`` so the pipeline needs nothing beyond the standard library. The first header cell carries a
byte-order mark, and the last header cell is ``Version:<year> <Mon> <day> - <time> UTC``, which is
the only place the file states its own release.

The id, parent, and class rules mirror the audited loader in the sibling ``ciel-scripts``
repository (``ocl_uploader_icd11.py``), with one deliberate difference: parents are resolved in a
second pass, so a parent that appears later in the file than its child is still found instead of
silently falling back to the chapter. Nothing is inferred from lexical similarity; every concept
comes from exactly one row.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT_ID = "ICD-11-Root"
ROOT_NAME = "ICD-11 Root"
ROOT_DESCRIPTION = "Root concept for ICD-11 WHO classification"

CLASS_BY_KIND = {"chapter": "Chapter", "block": "Block", "category": "Diagnosis"}
FALLBACK_CLASS = "Diagnosis"
MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}
VERSION_RE = re.compile(r"Version:\s*(\d{4})\s+(\w+)\s+(\d+)")
URL_RE = re.compile(r'https?://[^"]+')
REQUIRED_COLUMNS = ("Foundation URI", "Linearization URI", "Code", "BlockId", "Title", "ClassKind")


@dataclass(frozen=True)
class Row:
    """One entity of the tabulation, with every field verbatim except the documented title cleanup."""

    id: str
    code: str
    title: str
    class_kind: str
    parent: str | None
    foundation_uri: str
    linearization_uri: str
    block_id: str
    depth_in_kind: str
    is_residual: str
    chapter_no: str
    browser_link: str
    is_leaf: str
    source_row: int

    @property
    def concept_class(self) -> str:
        return CLASS_BY_KIND.get(self.class_kind.lower(), FALLBACK_CLASS)


@dataclass
class Tabulation:
    release: str  # e.g. "2026-01" (year-month, from the Version header)
    version_label: str  # the header text verbatim, e.g. "Version:2026 Jan 17 - 05:30 UTC"
    rows: list[Row] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)


def normalize_title(title: str) -> str:
    """Drop the leading ``- `` depth markers the tabulation prefixes to block titles."""
    return re.sub(r"^[- ]+", "", title or "").strip()


def normalize_browser_link(value: str, release: str | None) -> str:
    """Extract the URL from the ``=hyperlink(...)`` cell and pin it to the release instead of ``latestrelease``."""
    text = (value or "").strip()
    match = URL_RE.search(text)
    if not match:
        return text
    url = match.group(0)
    if release:
        url = url.replace("/browse/latestrelease/", f"/browse/{release}/")
    return url


def _after(uri: str, marker: str) -> str:
    uri = (uri or "").strip()
    return uri.split(marker, 1)[1].strip().strip("/") if marker in uri else ""


def resolve_id(code: str, block_id: str, class_kind: str, chapter_no: str, linearization_uri: str) -> str:
    """ID fallback order: Code, BlockId, ``Chapter-<ChapterNo>`` for a chapter, then the ``/mms/`` suffix."""
    if code:
        return code
    if block_id:
        return block_id
    if class_kind == "chapter" and chapter_no:
        return f"Chapter-{chapter_no}"
    return _after(linearization_uri, "/mms/")


def _release_from_header(headers: list[str]) -> tuple[str, str]:
    for header in headers:
        match = VERSION_RE.search(header or "")
        if match:
            year, month, _day = match.groups()
            return f"{year}-{MONTHS.get(month, '01')}", header.strip()
    raise ValueError("no 'Version:' cell in the header row; this is not a Simple Tabulation file")


def _open_text(path: Path) -> io.TextIOWrapper:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Simple Tabulation input not found: {path}")
    if path.suffix.lower() != ".zip":
        return path.open("r", encoding="utf-8-sig", newline="")
    archive = zipfile.ZipFile(path)
    members = [name for name in archive.namelist() if name.lower().endswith(".txt") and "readme" not in name.lower()]
    if not members:
        raise ValueError(f"{path}: no tab-separated .txt member in the archive")
    return io.TextIOWrapper(archive.open(sorted(members)[0]), encoding="utf-8-sig", newline="")


def read(path: Path) -> Tabulation:
    """Read a Simple Tabulation ``.zip`` or ``.txt`` into ordered rows, recording what was skipped."""
    with _open_text(path) as stream:
        reader = csv.reader(stream, delimiter="\t", quotechar='"')
        headers = [cell.strip() for cell in next(reader)]
        release, version_label = _release_from_header(headers)
        index = {name: position for position, name in enumerate(headers) if name}
        missing = [name for name in REQUIRED_COLUMNS if name not in index]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        grouping_columns = [index[name] for name in (f"Grouping{n}" for n in range(1, 6)) if name in index]

        def cell(row: list[str], name: str) -> str:
            position = index.get(name)
            return row[position].strip() if position is not None and position < len(row) else ""

        tabulation = Tabulation(release=release, version_label=version_label)
        raw: list[tuple[Row, list[str], str]] = []
        for number, row in enumerate(reader, start=2):
            code = cell(row, "Code")
            block_id = cell(row, "BlockId")
            class_kind = cell(row, "ClassKind")
            chapter_no = cell(row, "ChapterNo")
            linearization_uri = cell(row, "Linearization URI")
            concept_id = resolve_id(code, block_id, class_kind, chapter_no, linearization_uri)
            if not concept_id:
                # Editorial notes and blank spacer lines carry none of the supported identifiers.
                tabulation.skipped.append({"reason": "no-supported-identifier", "source_row": number})
                continue
            groupings = [row[p].strip() for p in grouping_columns if p < len(row) and row[p].strip()]
            raw.append(
                (
                    Row(
                        id=concept_id,
                        code=code,
                        title=normalize_title(cell(row, "Title")),
                        class_kind=class_kind,
                        parent=None,  # resolved below
                        foundation_uri=cell(row, "Foundation URI"),
                        linearization_uri=linearization_uri,
                        block_id=block_id,
                        depth_in_kind=cell(row, "DepthInKind"),
                        is_residual=cell(row, "IsResidual"),
                        chapter_no=chapter_no,
                        browser_link=normalize_browser_link(cell(row, "BrowserLink"), release),
                        is_leaf=cell(row, "isLeaf"),
                        source_row=number,
                    ),
                    groupings,
                    cell(row, "Parent"),
                )
            )

    # Foundation URI -> concept id, over the whole file (second pass: order does not matter).
    by_foundation: dict[str, str] = {}
    for row, _groupings, _parent_uri in raw:
        if row.foundation_uri:
            by_foundation[row.foundation_uri] = row.id
            entity = _after(row.foundation_uri, "/entity/")
            if entity:
                by_foundation[entity] = row.id

    seen: set[str] = set()
    for row, groupings, parent_uri in raw:
        if row.id in seen:
            tabulation.duplicate_ids.append(row.id)
        seen.add(row.id)
        parent: str | None
        if row.class_kind == "chapter":
            parent = None
        elif row.code and "." in row.code:
            # A sub-code (1A03.0) belongs directly under its stem (1A03), which never appears in the
            # Grouping columns.
            parent = row.id.split(".", 1)[0].strip() or None
        else:
            parent = next((g for g in reversed(groupings) if g != row.id), None)
        if parent is None and parent_uri:
            parent = by_foundation.get(parent_uri) or by_foundation.get(_after(parent_uri, "/entity/"))
        if parent is None and row.class_kind != "chapter" and row.chapter_no:
            parent = f"Chapter-{row.chapter_no}"
        tabulation.rows.append(
            Row(**{**row.__dict__, "parent": parent})
        )
    return tabulation
