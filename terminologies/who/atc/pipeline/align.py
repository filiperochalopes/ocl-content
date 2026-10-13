"""Compare the BioPortal-derived ATC snapshot against a live export of ``WHO/WHOATC``.

This never retires or changes anything by itself: it classifies every code into a review status and
writes a CSV a curator reads before deciding what, if anything, should be retired. "Missing from the
fresh ontology" is a **candidate**, not a verdict — BioPortal's ATC submission lags the official
atcddd.fhi.no ATC/DDD Index (see ``README.md``, "Known limits"), so an absence can mean WHO retired
the code, or it can mean BioPortal has not caught up yet. Cross-check a candidate against the
cumulative alterations list (``atcddd_alterations.py``) and, for anything not explained there,
against atcddd.fhi.no directly before retiring it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .ttl_reader import AtcOntology

STATUS_NEW = "new-in-ontology"
STATUS_PRESENT = "present-in-both-no-name-comparison"
STATUS_UNCHANGED = "unchanged"
STATUS_NAME_CHANGED = "name-changed"
STATUS_MISSING_CANDIDATE = "missing-from-ontology-retire-candidate"
STATUS_ALREADY_RETIRED = "already-retired-in-export"


@dataclass(frozen=True)
class AlignmentRow:
    code: str
    status: str
    ontology_title: str | None
    export_title: str | None
    export_retired: bool | None


def _fsn(resource: dict) -> str | None:
    for name in resource.get("names") or []:
        if name.get("name_type") in ("Fully Specified", "FULLY_SPECIFIED") and name.get("name"):
            return name["name"]
    names = resource.get("names") or []
    return names[0].get("name") if names else None


def align(ontology: AtcOntology, export_concepts: dict[str, dict]) -> list[AlignmentRow]:
    """``export_concepts`` is ``{concept id: concept resource}``, e.g. from ``tools/ocl_export.py``."""
    ontology_by_code = {entry.code: entry for entry in ontology.classes}
    rows: list[AlignmentRow] = []

    for code, entry in sorted(ontology_by_code.items()):
        resource = export_concepts.get(code)
        if resource is None:
            rows.append(AlignmentRow(code, STATUS_NEW, entry.title, None, None))
            continue
        export_title = _fsn(resource)
        retired = bool(resource.get("retired"))
        if retired:
            # The export already marks it retired; the ontology considers it live again.
            rows.append(AlignmentRow(code, STATUS_NEW, entry.title, export_title, retired))
        elif "names" not in resource:
            # GET /concepts/ list snapshots deliberately carry only display_name, not a complete names
            # collection. An exact code/lifecycle diff can still be trusted, but no lexical judgment can.
            rows.append(AlignmentRow(code, STATUS_PRESENT, entry.title, resource.get("display_name"), retired))
        elif export_title == entry.title:
            rows.append(AlignmentRow(code, STATUS_UNCHANGED, entry.title, export_title, retired))
        else:
            rows.append(AlignmentRow(code, STATUS_NAME_CHANGED, entry.title, export_title, retired))

    for code, resource in sorted(export_concepts.items()):
        if code in ontology_by_code or code == "Root":
            continue
        retired = bool(resource.get("retired"))
        status = STATUS_ALREADY_RETIRED if retired else STATUS_MISSING_CANDIDATE
        rows.append(AlignmentRow(code, status, None, _fsn(resource), retired))

    return rows


def write_csv(path: Path, rows: list[AlignmentRow]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["code", "status", "ontology_title", "export_title", "export_retired"])
        for row in rows:
            writer.writerow([row.code, row.status, row.ontology_title or "", row.export_title or "", row.export_retired])


def summarize(rows: list[AlignmentRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return dict(sorted(counts.items()))
