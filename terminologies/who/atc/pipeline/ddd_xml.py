"""Read the WHOCC ``ATC_ddd.xml`` release file and project it to the ``DDD`` concept extra.

The release file is an ADO rowset: one ``<z:row ATCCode=... DDD=... UnitType=... AdmCode=...
DDDComment=.../>`` element per DDD row, with the row attributes in the ``#RowsetSchema`` namespace.
Attributes may be missing or empty, codes and values may carry stray whitespace, and a code may
repeat (several routes, several formulations of one route told apart only by ``DDDComment``).

Owner decisions this module encodes (2026-10-15):

* ``DDD`` is one string extra per concept, one entry per XML row, in file order.
* A line is ``<DDD> <unit> (<route>) <comment>``: a space between value and unit, the route in
  parentheses, the comment last. Missing parts are omitted, never invented.
* A row with an empty ``DDD`` value writes nothing; a code whose rows are all empty gets no extra.
* Partial rows (no unit, no route) are kept as published and counted in the audit.

Open (kept in one place each so they can change without touching the logic): ``LINE_SEPARATOR``
and the route expansion in ``ROUTE_LABELS``. The route legend is the WHOCC's own, published on
the ATC/DDD Index page (https://atcddd.fhi.no/atc_ddd_index/, "Route of administration (Adm.R)").
Route values outside the legend (``Inhal.solution``, ``Chewing gum``, ``implant``...) are kept
verbatim, and the audit counts them.

Stdlib only; makes no network call.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

ROW_TAG = "{#RowsetSchema}row"
LINE_SEPARATOR = "; "  # the web UI collapses a newline into a space; see README

# Exact-case keys from the WHOCC legend (Adm.R). SL's definition is quoted as published.
ROUTE_LABELS = {
    "Implant": "implant",
    "Inhal": "inhalation",
    "Instill": "instillation",
    "N": "nasal",
    "O": "oral",
    "P": "parenteral",
    "R": "rectal",
    "SL": "sublingual/buccal/oromucosal",
    "TD": "transdermal",
    "V": "vaginal",
}


@dataclass(frozen=True)
class DddRow:
    """One DDD row with whitespace normalised; ``row`` is its 1-based position in the file."""

    row: int
    code: str
    ddd: str
    unit: str
    route: str
    comment: str


@dataclass(frozen=True)
class DddResult:
    """``extras`` maps a code to its ``DDD`` string; the counters feed the audit."""

    extras: dict[str, str]
    stats: dict[str, object]


def _clean(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def read_rows(path: Path) -> list[DddRow]:
    """Parse the rowset; reject a file that is not the expected shape instead of guessing."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"{path}: not well-formed XML: {error}") from error
    rows: list[DddRow] = []
    for position, element in enumerate(root.iter(ROW_TAG), start=1):
        attributes = element.attrib
        unknown = set(attributes) - {"ATCCode", "DDD", "UnitType", "AdmCode", "DDDComment"}
        if unknown:
            raise ValueError(f"{path}: row {position} has unexpected attributes {sorted(unknown)}")
        code = _clean(attributes.get("ATCCode"))
        if not code:
            raise ValueError(f"{path}: row {position} has no ATCCode")
        rows.append(DddRow(
            row=position,
            code=code,
            ddd=_clean(attributes.get("DDD")),
            unit=_clean(attributes.get("UnitType")),
            route=_clean(attributes.get("AdmCode")),
            comment=_clean(attributes.get("DDDComment")),
        ))
    if not rows:
        raise ValueError(f"{path}: no <z:row> elements found; is this the WHOCC ATC_ddd.xml?")
    return rows


def format_row(row: DddRow) -> str | None:
    """Render one row, or ``None`` when it has no DDD value."""
    if not row.ddd:
        return None
    text = f"{row.ddd} {row.unit}" if row.unit else row.ddd
    if row.route:
        text += f" ({ROUTE_LABELS.get(row.route, row.route)})"
    if row.comment:
        text += f" {row.comment}"
    return text


def project(rows: list[DddRow], known_codes: set[str]) -> DddResult:
    """Group rows by code and build each ``DDD`` string; abort on a code absent from the release."""
    unknown = sorted({row.code for row in rows} - known_codes)
    if unknown:
        raise ValueError(
            f"DDD file names {len(unknown)} code(s) absent from the WHOCC snapshot: {unknown[:10]}"
        )
    lines: dict[str, list[str]] = {}
    skipped_empty: list[str] = []
    partial = {"no_unit": 0, "no_route": 0}
    unlisted_routes: Counter[str] = Counter()
    for row in rows:
        text = format_row(row)
        if text is None:
            skipped_empty.append(row.code)
            continue
        lines.setdefault(row.code, []).append(text)
        partial["no_unit"] += not row.unit
        partial["no_route"] += not row.route
        if row.route and row.route not in ROUTE_LABELS:
            unlisted_routes[row.route] += 1
    extras = {code: LINE_SEPARATOR.join(parts) for code, parts in lines.items()}
    codes_in_file = {row.code for row in rows}
    return DddResult(
        extras=extras,
        stats={
            "ddd_rows": len(rows),
            "ddd_rows_written": sum(len(parts) for parts in lines.values()),
            "codes_in_file": len(codes_in_file),
            "codes_with_ddd": len(extras),
            "rows_skipped_empty_ddd": len(skipped_empty),
            "codes_skipped_empty_ddd": sorted(set(skipped_empty) - set(extras)),
            "written_rows_without_unit": partial["no_unit"],
            "written_rows_without_route": partial["no_route"],
            "routes_outside_whocc_legend": dict(sorted(unlisted_routes.items())),
            "line_separator": LINE_SEPARATOR,
        },
    )
