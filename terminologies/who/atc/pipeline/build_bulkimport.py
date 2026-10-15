"""Build active WHO-ATC concepts for ``WHO/WHOATC`` from the BioPortal ATC ontology export.

The historical sibling loader (`ciel-scripts/ocl_uploader_whoatc.py`) also inferred retirements and
``REPLACED BY`` mappings from atcddd.fhi.no's cumulative alterations page. That page is a useful
cross-check but **not the authority for this Source's lifecycle decisions**, so this pipeline does
neither: the active full-load artifact contains the active ontology classes plus the synthetic root,
and no mapping resources. Retirements are a separate, audited update built only from the difference
between a current upstream ontology and an immutable snapshot of the previous OCL Source state.

The build is local and deterministic: it never calls OCL and never performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .ttl_reader import AtcClass, AtcOntology

TARGET_OWNER = "WHO"
TARGET_SOURCE = "WHOATC"
OWNER_TYPE = "Organization"
NAME_TYPE_FSN = "Fully Specified"
DATATYPE = "None"  # the OCL-valid value; see module docstring for why this is not the script's "N/A"

ROOT_ID = "Root"
ROOT_NAME = "Root"
ROOT_DESCRIPTION = "Root concept for WHO ATC classification"

LEVEL_CLASS = {1: "Chapter", 2: "Group", 3: "Subgroup", 4: "Subgroup", 5: "Code"}


def concept_url(concept_id: str) -> str:
    return f"/orgs/{TARGET_OWNER}/sources/{TARGET_SOURCE}/concepts/{quote(concept_id, safe='')}/"


def concept_class_for(level: int) -> str:
    try:
        return LEVEL_CLASS[level]
    except KeyError:
        raise ValueError(f"unexpected ATC level {level!r}; expected 1-5") from None


def root_line() -> dict:
    return {
        "type": "Concept",
        "id": ROOT_ID,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": "Root",
        "datatype": DATATYPE,
        "retired": False,
        "names": [{"name": ROOT_NAME, "locale": "en", "locale_preferred": True, "name_type": NAME_TYPE_FSN}],
        "descriptions": [
            {"description": ROOT_DESCRIPTION, "locale": "en", "locale_preferred": True, "type": "Definition"}
        ],
    }


def concept_line(entry: AtcClass) -> dict:
    names = [{"name": entry.title, "locale": "en", "locale_preferred": True, "name_type": NAME_TYPE_FSN}]

    descriptions = []  # no UMLS CUI note: UMLS is out of every output until the TBD.md decision

    is_drug_class = entry.is_drug_class or ("Y" if entry.level != 5 else "N")
    extras = {
        "ATC Level": int(entry.level),
        "Is_Drug_Class": is_drug_class,
    }
    extras = {key: value for key, value in extras.items() if value not in ("", [], None)}

    parent = ROOT_ID if entry.level == 1 or not entry.parent else entry.parent
    return {
        "type": "Concept",
        "id": entry.code,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": concept_class_for(entry.level),
        "datatype": DATATYPE,
        "retired": False,
        "names": names,
        "descriptions": descriptions,
        "extras": extras,
        "parent_concept_urls": [concept_url(parent)],
    }



@dataclass
class BuildResult:
    lines: list[dict]
    class_counts: dict[str, int]


def build(ontology: AtcOntology) -> BuildResult:
    if ontology.duplicate_codes:
        raise ValueError(
            f"{len(ontology.duplicate_codes)} duplicate ATC codes in the ontology, "
            f"e.g. {ontology.duplicate_codes[:5]}; a bulk import would overwrite one with the other"
        )
    codes = {entry.code for entry in ontology.classes}
    if ROOT_ID in codes:
        raise ValueError(f"the ontology already contains a class with the reserved root id {ROOT_ID!r}")

    lines = [root_line()] + [concept_line(entry) for entry in sorted(ontology.classes, key=lambda item: (item.level, item.code))]
    counts: dict[str, int] = {}
    for line in lines:
        counts[line["concept_class"]] = counts.get(line["concept_class"], 0) + 1
    return BuildResult(lines=lines, class_counts=dict(sorted(counts.items())))
