"""Build a full ICD-10-CM FY27 OCL Source from Tabular XML plus the concrete order-code list."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from .release import Release

TARGET_OWNER = "US-NCHS"
TARGET_SOURCE = "ICD-10-CM"
OWNER_TYPE = "Organization"
ROOT_ID = "ICD-10-CM"
ROOT_NAME = "ICD-10-CM TABULAR LIST of DISEASES and INJURIES"


def concept_url(code: str) -> str:
    return f"/orgs/{TARGET_OWNER}/sources/{TARGET_SOURCE}/concepts/{quote(code, safe='')}/"


def root_line() -> dict:
    return {"type": "Concept", "id": ROOT_ID, "owner": TARGET_OWNER, "owner_type": OWNER_TYPE, "source": TARGET_SOURCE,
            "concept_class": "Root", "datatype": "None", "retired": False,
            "names": [{"name": ROOT_NAME, "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}],
            "extras": {"Leaf Node": False}}


@dataclass(frozen=True)
class BuildResult:
    lines: list[dict]
    diagnosis_codes: int
    chapter_nodes: int
    section_nodes: int


def build(release: Release) -> BuildResult:
    children: dict[str, list[str]] = {}
    for node in release.nodes.values():
        if node.parent:
            children.setdefault(node.parent, []).append(node.code)
    for code in release.codes.values():
        children.setdefault(code.parent, []).append(code.code)

    lines = [root_line()]
    for code in release.node_order:
        node = release.nodes[code]
        if node.kind == "diag":
            continue  # concrete diagnosis rows below supply the authoritative order-file descriptions
        parent = ROOT_ID if node.kind == "chapter" else node.parent
        concept_class = "Chapter" if node.kind == "chapter" else "Section"
        lines.append({"type": "Concept", "id": node.code, "owner": TARGET_OWNER, "owner_type": OWNER_TYPE, "source": TARGET_SOURCE,
                      "concept_class": concept_class, "datatype": "None", "retired": False,
                      "names": [{"name": node.title, "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}],
                      "extras": {"Leaf Node": not bool(children.get(node.code))},
                      "parent_concept_urls": [concept_url(parent)]})
    for code in release.code_order:
        item = release.codes[code]
        lines.append({"type": "Concept", "id": item.code, "owner": TARGET_OWNER, "owner_type": OWNER_TYPE, "source": TARGET_SOURCE,
                      "concept_class": "Diagnosis", "datatype": "None", "retired": False,
                      "names": [{"name": item.long_description, "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}],
                      "extras": {"Order number": item.order_number, "Valid for submission": item.valid_for_submission,
                                 "Leaf Node": not bool(children.get(item.code))},
                      "parent_concept_urls": [concept_url(item.parent)]})
    positions = {line["id"]: index for index, line in enumerate(lines)}
    problems = [line["id"] for line in lines[1:] if positions[line["parent_concept_urls"][0].rstrip('/').rsplit('/', 1)[1]] >= positions[line["id"]]]
    if problems:
        raise ValueError(f"{len(problems)} hierarchy parent(s) come after children, e.g. {problems[:5]}")
    return BuildResult(lines, len(release.codes), sum(n.kind == "chapter" for n in release.nodes.values()), sum(n.kind == "section" for n in release.nodes.values()))



NAME_KEYS = ("name", "locale", "locale_preferred", "name_type")
FY_EXTRAS = ("Order number", "Valid for submission", "Leaf Node")
SEMANTIC_TYPE_ID = re.compile(r"T\d{3}")
UMLS_EXTRAS = ("CUI", "Semantic Types")


def _clean_name(name: dict) -> dict:
    """Keep only importable fields: uuid/checksum/type are server-owned and ``external_id`` is not used here."""
    return {key: name[key] for key in NAME_KEYS if key in name}


@dataclass
class UpdateResult:
    lines: list[dict]
    stats: dict = field(default_factory=dict)
    not_in_release: dict = field(default_factory=dict)


def project_update(result: BuildResult, existing: dict[str, dict]) -> UpdateResult:
    """Turn the full-release lines into an update against one environment's own export.

    The bulk importer rebuilds ``names`` and replaces ``extras`` wholesale, so a line for a concept the target
    already holds must carry everything the release does not govern: the existing non-preferred names
    (English synonyms), descriptions, and every legacy extra (CUI, Semantic Types, EXCLUDES1/2, USE ADDITIONAL,
    CODE FIRST, CODE ALSO, Note). Only the English preferred name, ``Order number``, ``Valid for submission``,
    ``Leaf Node``, the parent link and the ``concept_class`` (Root/Chapter/Section/Diagnosis, as decided for
    FY27) come from the release; ``datatype`` too. Ids absent from the release are reported, never retired here.

    UMLS is out of every update until the decision in ``TBD.md`` says otherwise: ``CUI`` and ``Semantic Types`` are
    not carried (OCL replaces ``extras`` wholesale, so they disappear from each updated concept) and one
    ``__action: "DELETE"`` (retirement) line is appended per active ``T001``-``T204`` concept, which are UMLS
    Semantic Type identifiers and not ICD-10-CM codes. Other ids absent from the release are only reported.
    """
    lines, st = [], {"existing_updated": 0, "created": 0, "preferred_name_changed": 0, "synonyms_preserved": 0,
                     "concepts_with_synonyms": 0, "legacy_extras_preserved": 0, "parent_changed": 0, "extras_values_changed": 0, "concept_class_changed": 0, "umls_extras_dropped": 0, "semantic_type_concepts_retired": 0}
    release_ids = set()
    for line in result.lines:
        release_ids.add(line["id"])
        old = existing.get(line["id"])
        if old is None:
            st["created"] += 1
            lines.append(line)
            continue
        out = dict(line)
        preferred = [n for n in old.get("names", []) if n.get("locale_preferred") and n.get("locale") == "en"]
        keep = [_clean_name(n) for n in old.get("names", []) if n not in preferred]
        if preferred and preferred[0].get("name") != line["names"][0]["name"]:
            st["preferred_name_changed"] += 1
        out["names"] = list(line["names"]) + keep
        if keep:
            st["concepts_with_synonyms"] += 1
            st["synonyms_preserved"] += len(keep)
        if old.get("descriptions"):
            out["descriptions"] = [{k: v for k, v in d.items() if k in ("description", "locale", "locale_preferred", "description_type")} for d in old["descriptions"]]
        legacy = {k: v for k, v in (old.get("extras") or {}).items() if k not in FY_EXTRAS}
        st["umls_extras_dropped"] += sum(k in legacy for k in UMLS_EXTRAS)
        legacy = {k: v for k, v in legacy.items() if k not in UMLS_EXTRAS}
        st["legacy_extras_preserved"] += len(legacy)
        before_fy = {k: (old.get("extras") or {}).get(k) for k in FY_EXTRAS}
        out["extras"] = {**legacy, **line["extras"]}
        if any(before_fy.get(k) != line["extras"].get(k) for k in FY_EXTRAS):
            st["extras_values_changed"] += 1
        if old.get("concept_class") != line["concept_class"]:
            st["concept_class_changed"] += 1
        if set(old.get("parent_concept_urls") or []) != set(line.get("parent_concept_urls") or []):
            st["parent_changed"] += 1
        st["existing_updated"] += 1
        lines.append(out)
    gone = sorted(i for i, c in existing.items() if i not in release_ids and not c.get("retired"))
    for i in gone:
        if SEMANTIC_TYPE_ID.fullmatch(i):
            old = existing[i]
            lines.append({"type": "Concept", "id": i, "owner": old.get("owner") or "US-NCHS", "owner_type": "Organization",
                          "source": old.get("source") or "ICD-10-CM", "concept_class": old.get("concept_class") or "Diagnosis",
                          "__action": "DELETE"})
            st["semantic_type_concepts_retired"] += 1
    buckets = {"semantic_type_ids": [i for i in gone if SEMANTIC_TYPE_ID.fullmatch(i)],
               "synthetic_ranges": [i for i in gone if "-" in i],
               "other_codes": [i for i in gone if not SEMANTIC_TYPE_ID.fullmatch(i) and "-" not in i]}
    return UpdateResult(lines, st, buckets)
