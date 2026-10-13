"""Audited retirement update for existing WHO/WHOATC concepts.

Lifecycle evidence is deliberately narrow: a concept is proposed for retirement **only** when it is
active in the immutable previous OCL snapshot and its exact code is absent from the current BioPortal
ATC ontology. The atcddd.fhi.no alterations list is not read here, and this module never emits a
mapping. A lexical or label difference is never a retirement criterion.

The OCL bulk importer replaces collection fields, so each retirement line preserves the source
concept's complete names, descriptions, and extras; the only intended change is top-level
``retired: false`` → ``true``. Before/after arrays use the same projection and ID order so a
JSON-aware diff shows exactly that field transition.
"""

from __future__ import annotations

from dataclasses import dataclass

from .build_bulkimport import OWNER_TYPE, TARGET_OWNER, TARGET_SOURCE
from .ttl_reader import AtcOntology

NAME_FIELDS = ("name", "locale", "locale_preferred", "name_type", "retired")
DESCRIPTION_FIELDS = ("description", "locale", "locale_preferred", "type", "retired")


def _pick(resource: dict, fields: tuple[str, ...]) -> dict:
    return {field: resource[field] for field in fields if field in resource and resource[field] is not None}


def _project_name(name: dict) -> dict:
    return _pick(name, NAME_FIELDS)


def _project_description(description: dict) -> dict:
    projected = _pick(description, DESCRIPTION_FIELDS)
    if description.get("description_type") is not None:
        projected["type"] = description["description_type"]
    return projected


def project(resource: dict, *, retired: bool) -> dict:
    """The single import-relevant projection used in the before audit, after audit, and NDJSON."""
    concept_id = str(resource.get("id") or "")
    if not concept_id:
        raise ValueError("concept resource without an id")
    return {
        "type": "Concept",
        "id": concept_id,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": resource.get("concept_class"),
        "datatype": resource.get("datatype"),
        "retired": retired,
        "names": [_project_name(name) for name in resource.get("names") or [] if isinstance(name, dict)],
        "descriptions": [
            _project_description(description)
            for description in resource.get("descriptions") or []
            if isinstance(description, dict)
        ],
        "extras": dict(resource.get("extras") or {}),
    }


@dataclass(frozen=True)
class RetirementResult:
    before: list[dict]
    after: list[dict]
    candidate_ids: list[str]
    ignored_already_retired: list[str]


def build(ontology: AtcOntology, snapshot: dict[str, dict]) -> RetirementResult:
    upstream_codes = {entry.code for entry in ontology.classes}
    candidate_ids: list[str] = []
    already_retired: list[str] = []
    for concept_id, resource in sorted(snapshot.items()):
        if concept_id == "Root" or concept_id in upstream_codes:
            continue
        if resource.get("retired"):
            already_retired.append(concept_id)
            continue
        candidate_ids.append(concept_id)

    before = [project(snapshot[concept_id], retired=False) for concept_id in candidate_ids]
    after = [project(snapshot[concept_id], retired=True) for concept_id in candidate_ids]
    if [row["id"] for row in before] != [row["id"] for row in after]:
        raise AssertionError("before/after ID sequences diverged")
    return RetirementResult(before=before, after=after, candidate_ids=candidate_ids, ignored_already_retired=already_retired)
