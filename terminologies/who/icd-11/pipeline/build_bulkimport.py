"""Build the OCL bulk-import lines for the ICD-11 base Source from the Simple Tabulation.

One line per entity, in the order of the tabulation, preceded by the synthetic root. Every line
carries ``owner``, ``owner_type``, ``source``, ``concept_class``, ``datatype``, ``retired``,
``names`` (one English *Fully Specified* name), ``extras``, and the ``parent_concept_urls`` that
build the hierarchy. There is no ``Source`` record. The Source is expected to exist already (see
``source.json``).

Because the whole content is derived from one release, a rebuild from the same file is
byte-identical. The build refuses to emit lines whose parent is missing or comes later than the
child, since OCL imports lines in order.

``build_postcoordinated`` below is a separate layer: indexed post-coordinated codes
(``pipeline/postcoordinated.py``), each a ``Diagnosis`` concept carrying its own composite WHO code
(with ``&``/``/`` kept, not encoded) plus a ``NARROWER-THAN`` mapping to its first stem — never a
``parent_concept_urls`` change, so it never touches the base hierarchy built above. It can be written
as its own additive bundle or appended to the base lines to form a single bundle.

Aliases (owner decision): extra names from WHO Foundation entities are written as names WITHOUT a
``name_type`` — the key is omitted, so OCL stores null; the string ``"None"`` is never written. They
are lexical aliases of the Foundation entities, not a claim of semantic equivalence: the flat-code
entities are narrower or residual roll-ups of the code. The Fully Specified name always comes first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import quote

from .foundation_index import entity_names
from .postcoordinated import PostcoordIndex, public_browse_url
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


FOUNDATION_ID_RE = re.compile(r"/entity/(\d+)$")


def foundation_uri(foundation_id: str) -> str:
    """The standard WHO Foundation entity URI (API identifier; the browser needs the URL below)."""
    return f"http://id.who.int/icd/entity/{foundation_id}"


def foundation_url(release: str, foundation_id: str) -> str:
    """The official, release-pinned WHO Foundation browser link for one Foundation entity id."""
    return f"https://icd.who.int/browse/{release}/foundation/en#{foundation_id}"


def foundation_id_of(foundation_uri: str) -> str:
    """Entity id from ``http://id.who.int/icd/entity/<id>``, or ``""`` when the URI has another shape."""
    match = FOUNDATION_ID_RE.search(foundation_uri or "")
    return match.group(1) if match else ""


def alias_name_entry(name: str) -> dict:
    """An untyped English alias: no ``name_type`` key (null in OCL), never preferred."""
    return {"name": name, "locale": "en", "locale_preferred": False}


def unique_aliases(fsn: str, candidates: Iterable[str]) -> tuple[list[str], int]:
    """Aliases in order, without case-insensitive repeats; also returns how many equalled the FSN."""
    seen = {fsn.casefold()}
    kept: list[str] = []
    equal_to_fsn = 0
    for name in candidates:
        key = name.casefold()
        if key == fsn.casefold():
            equal_to_fsn += 1
        elif key not in seen:
            seen.add(key)
            kept.append(name)
    return kept, equal_to_fsn


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


def concept_line(row: Row, aliases: Iterable[str] = (), release: str = "") -> dict:
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
            {"name": row.title or row.id, "locale": "en", "locale_preferred": True, "name_type": NAME_TYPE},
            *(alias_name_entry(alias) for alias in aliases),
        ],
    }
    extras = {label: getattr(row, attribute) for label, attribute in EXTRA_FIELDS if getattr(row, attribute)}
    foundation_id = foundation_id_of(row.foundation_uri)
    if release and foundation_id:
        extras["Foundation URL"] = foundation_url(release, foundation_id)
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
    alias_stats: dict = field(default_factory=dict)


def build(tabulation: Tabulation, flat_aliases: dict[str, list] | None = None) -> BuildResult:
    """Build the base lines; ``flat_aliases`` maps a concept id to objects with a ``name`` attribute."""
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

    flat_aliases = flat_aliases or {}
    stats = {"names_added": 0, "concepts_with_aliases": 0, "equal_to_fsn": 0, "unknown_codes": []}
    concept_lines = []
    for row in tabulation.rows:
        kept, equal = unique_aliases(row.title or row.id, (alias.name for alias in flat_aliases.get(row.id, ())))
        stats["names_added"] += len(kept)
        stats["equal_to_fsn"] += equal
        stats["concepts_with_aliases"] += bool(kept)
        concept_lines.append(concept_line(row, kept, tabulation.release))
    stats["unknown_codes"] = sorted(set(flat_aliases) - set(position))
    lines = [root_line()] + concept_lines
    counts: dict[str, int] = {}
    for line in lines:
        counts[line["concept_class"]] = counts.get(line["concept_class"], 0) + 1
    return BuildResult(
        lines=lines, class_counts=dict(sorted(counts.items())), rooted_without_parent=rooted, alias_stats=stats,
    )


# --- post-coordinated add-on layer (separate from the base build above) ---------------------------

POSTCOORD_CONCEPT_CLASS = "Diagnosis"
POSTCOORD_NAME_TYPE = "Fully Specified"
MAP_TYPE_NARROWER_THAN = "NARROWER-THAN"


def postcoord_concept_line(row, alias_names: Iterable[str] = (), foundation_id: str = "", release: str = "") -> dict:
    if "&" not in row.code and "/" not in row.code:
        raise ValueError(f"{row.code!r} is not a composite code (no '&' or '/'): isPostcoordinated would be wrong")
    # Same shape as any other concept: a leaf with a WHO "latest" browser link and the pinned Foundation
    # link. The only post-coordination extra is isPostcoordinated, which holds exactly for ids that carry
    # an '&' or a '/' (no base id does).
    extras = {"isLeaf": "True"}
    link = public_browse_url(row.entity_id, "latestrelease")
    if link:
        extras["BrowserLink"] = link
    if foundation_id and release:
        extras["Foundation URI"] = foundation_uri(foundation_id)
        extras["Foundation URL"] = foundation_url(release, foundation_id)
    extras["isPostcoordinated"] = "True"
    return {
        "type": "Concept",
        "id": row.code,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": POSTCOORD_CONCEPT_CLASS,
        "datatype": "N/A",
        "retired": False,
        "names": [
            {"name": row.title or row.code, "locale": "en", "locale_preferred": True, "name_type": POSTCOORD_NAME_TYPE},
            *(alias_name_entry(alias) for alias in alias_names),
        ],
        "extras": extras,
    }


def postcoord_mapping_line(row) -> dict:
    """A ``NARROWER-THAN`` mapping from the post-coordinated code to its first stem.

    ``concept_url`` percent-encodes ``&``/``/`` (``quote(id, safe='')``): a raw ``/`` in
    ``from_concept_url`` is silently truncated at the first ``/`` by this OCL version
    (OpenConceptLab/ocl_issues#739), confirmed against a local instance before this was written.
    """
    return {
        "type": "Mapping",
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "map_type": MAP_TYPE_NARROWER_THAN,
        "from_concept_url": concept_url(row.code),
        "to_concept_url": concept_url(row.stem_code),
    }


@dataclass
class PostcoordBuildResult:
    concept_lines: list[dict]
    mapping_lines: list[dict]
    unknown_stems: list[str]
    alias_stats: dict = field(default_factory=dict)
    foundation_stats: dict = field(default_factory=dict)


def build_postcoordinated(
    index: PostcoordIndex, known_stem_ids: set[str], index_entities: dict[str, list] | None = None
) -> PostcoordBuildResult:
    """Build concept + ``NARROWER-THAN`` mapping lines for the indexed post-coordinated codes.

    ``known_stem_ids`` is every concept id already in the base Source (from the Simple Tabulation):
    a stem not found there would create a mapping to a concept this bundle never creates, so it is
    reported in ``unknown_stems`` and its row is skipped rather than silently imported half-linked.

    ``index_entities`` (composite URI -> Foundation entities of the ICD-API search index) supplies the
    aliases: every entity title and synonym the index attaches to the composite, then the CSV's own
    synonyms. A row whose composite is absent from a supplied index is reported, still built.
    """
    concept_lines: list[dict] = []
    mapping_lines: list[dict] = []
    unknown_stems: list[str] = []
    stats = {"names_added": 0, "rows_with_aliases": 0, "equal_to_fsn": 0, "rows_without_index_entities": []}
    foundation = {"from_own_entity": 0, "from_single_index_entity": 0, "ambiguous_not_set": 0,
                  "own_not_in_index": 0, "no_entity": 0}
    for row in index.rows:
        if row.stem_code not in known_stem_ids:
            unknown_stems.append(row.code)
            continue
        candidates: list[str] = []
        if index_entities is not None:
            entities = index_entities.get(row.entity_id)
            if entities:
                candidates.extend(entity_names(entities))
            else:
                stats["rows_without_index_entities"].append(row.code)
        candidates.extend(row.synonyms)
        entity_ids = [entity.foundation_id for entity in (index_entities or {}).get(row.entity_id, ())]
        if row.foundation_entity_id:  # the API's own entity for this composite wins
            foundation_id = row.foundation_entity_id
            foundation["from_own_entity"] += 1
            if index_entities is not None and entity_ids and foundation_id not in entity_ids:
                foundation["own_not_in_index"] += 1
        elif len(entity_ids) == 1:
            foundation_id = entity_ids[0]
            foundation["from_single_index_entity"] += 1
        else:  # several candidates: none is more "the" entity of the composite, so none is guessed
            foundation_id = ""
            foundation["ambiguous_not_set" if entity_ids else "no_entity"] += 1
        kept, equal = unique_aliases(row.title or row.code, candidates)
        stats["names_added"] += len(kept)
        stats["equal_to_fsn"] += equal
        stats["rows_with_aliases"] += bool(kept)
        concept_lines.append(postcoord_concept_line(row, kept, foundation_id, index.release))
        mapping_lines.append(postcoord_mapping_line(row))
    return PostcoordBuildResult(
        concept_lines=concept_lines, mapping_lines=mapping_lines, unknown_stems=unknown_stems, alias_stats=stats,
        foundation_stats=foundation,
    )
