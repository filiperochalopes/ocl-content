"""Build the OCL bulk-import lines for the ICD-11 base Source from the Simple Tabulation.

One line per entity, in the order of the tabulation, preceded by the synthetic root. Every line
carries ``owner``, ``owner_type``, ``source``, ``concept_class``, ``datatype``, ``retired``,
``names`` (one English *Fully Specified* name), ``extras``, and the ``parent_concept_urls`` that
build the hierarchy. There is no ``Source`` record and there are no mappings: the Source is
expected to exist already (see ``source.json``), and post-coordinated codes are out of scope.

Because the whole content is derived from one release, a rebuild from the same file is
byte-identical. The build refuses to emit lines whose parent is missing or comes later than the
child, since OCL imports lines in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .simple_tabulation import ROOT_DESCRIPTION, ROOT_ID, ROOT_NAME, Row, Tabulation

TARGET_OWNER = "WHO"
TARGET_SOURCE = "ICD-11-WHO"
OWNER_TYPE = "Organization"
NAME_TYPE = "Fully Specified"

EXTRA_FIELDS = (
    ("Foundation URI", "foundation_uri"),
    ("Linearization URI", "linearization_uri"),
    ("BlockId", "block_id"),
    ("DepthInKind", "depth_in_kind"),
    ("IsResidual", "is_residual"),
    ("ChapterNo", "chapter_no"),
    ("BrowserLink", "browser_link"),
    ("isLeaf", "is_leaf"),
)


def concept_url(concept_id: str) -> str:
    return f"/orgs/{TARGET_OWNER}/sources/{TARGET_SOURCE}/concepts/{quote(concept_id, safe='')}/"


def root_line() -> dict:
    return {
        "type": "Concept",
        "id": ROOT_ID,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": "Root",
        "datatype": "N/A",
        "retired": False,
        "names": [{"name": ROOT_NAME, "locale": "en", "locale_preferred": True, "name_type": NAME_TYPE}],
        "descriptions": [
            {"description": ROOT_DESCRIPTION, "locale": "en", "locale_preferred": True, "type": "Definition"}
        ],
    }


def concept_line(row: Row) -> dict:
    line = {
        "type": "Concept",
        "id": row.id,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": row.concept_class,
        "datatype": "N/A",
        "retired": False,
        "names": [
            {"name": row.title or row.id, "locale": "en", "locale_preferred": True, "name_type": NAME_TYPE}
        ],
    }
    extras = {label: getattr(row, attribute) for label, attribute in EXTRA_FIELDS if getattr(row, attribute)}
    if extras:
        line["extras"] = extras
    # A chapter, and any row without a resolvable parent, hangs under the synthetic root.
    parent = ROOT_ID if row.class_kind == "chapter" or not row.parent else row.parent
    line["parent_concept_urls"] = [concept_url(parent)]
    return line


@dataclass
class BuildResult:
    lines: list[dict]
    class_counts: dict[str, int]
    rooted_without_parent: int


def build(tabulation: Tabulation) -> BuildResult:
    if tabulation.duplicate_ids:
        raise ValueError(
            f"{len(tabulation.duplicate_ids)} duplicate concept ids in the tabulation, "
            f"e.g. {tabulation.duplicate_ids[:5]}; a bulk import would overwrite one with the other"
        )
    position = {row.id: index for index, row in enumerate(tabulation.rows)}
    if ROOT_ID in position:
        raise ValueError(f"the tabulation already contains a concept with the reserved id {ROOT_ID!r}")
    problems: list[str] = []
    rooted = 0
    for index, row in enumerate(tabulation.rows):
        if row.class_kind == "chapter":
            continue
        if not row.parent:
            rooted += 1
        elif row.parent not in position:
            problems.append(f"{row.id}: parent {row.parent!r} is not in the tabulation")
        elif position[row.parent] > index:
            problems.append(f"{row.id}: parent {row.parent!r} comes later in the file")
    if problems:
        raise ValueError(f"{len(problems)} hierarchy problems, e.g. {problems[:5]}")

    lines = [root_line()] + [concept_line(row) for row in tabulation.rows]
    counts: dict[str, int] = {}
    for line in lines:
        counts[line["concept_class"]] = counts.get(line["concept_class"], 0) + 1
    return BuildResult(lines=lines, class_counts=dict(sorted(counts.items())), rooted_without_parent=rooted)
