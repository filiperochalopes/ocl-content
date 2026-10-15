"""Project the WHOCC ATC/DDD Index snapshot into an audited WHOATC Source update.

The input snapshot is produced by :mod:`atcddd_index` and is deliberately local: this module makes
no network calls. Every WHOCC record becomes the sole preferred English name of a concept, with the
two permitted derived fields (ATC level and drug-class flag). Active local concepts absent from the
WHOCC exact-code set, and active legacy mappings, are retired in the same ordered bulk-import bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import build_bulkimport as base


@dataclass(frozen=True)
class WhoRecord:
    """One validated record from the reproducible WHOCC index snapshot."""

    code: str
    title: str
    level: int
    parent: str | None


@dataclass(frozen=True)
class UpdateResult:
    """Complete ordered payload plus the classification counts recorded in the audit."""

    lines: list[dict[str, Any]]
    stats: dict[str, int]


def _require_text(item: dict[str, Any], key: str, context: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: {key} must be a non-empty string")
    return value


def records_from_snapshot(snapshot: dict[str, Any]) -> list[WhoRecord]:
    """Validate and order the WHOCC records stored by ``crawl-index``."""
    raw_records = snapshot.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError("WHOCC snapshot must contain a non-empty records list")

    records: list[WhoRecord] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_records):
        context = f"WHOCC snapshot record {index}"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object")
        code = _require_text(item, "code", context)
        title = _require_text(item, "title", context)
        level = item.get("level")
        parent = item.get("parent")
        if not isinstance(level, int) or level not in base.LEVEL_CLASS:
            raise ValueError(f"{context}: level must be an integer from 1 through 5")
        if parent is not None and (not isinstance(parent, str) or not parent):
            raise ValueError(f"{context}: parent must be null or a non-empty string")
        if code in seen:
            raise ValueError(f"WHOCC snapshot repeats code {code!r}")
        if code == base.ROOT_ID:
            raise ValueError(f"WHOCC snapshot reserves code {base.ROOT_ID!r} for the synthetic root")
        seen.add(code)
        records.append(WhoRecord(code=code, title=title, level=level, parent=parent))

    codes = {record.code for record in records}
    for record in records:
        if record.level == 1:
            if record.parent is not None:
                raise ValueError(f"WHOCC level-1 record {record.code!r} must not have a parent")
        elif record.parent not in codes:
            raise ValueError(f"WHOCC record {record.code!r} names missing parent {record.parent!r}")

    declared_total = snapshot.get("counts", {}).get("total") if isinstance(snapshot.get("counts"), dict) else None
    if declared_total is not None and declared_total != len(records):
        raise ValueError(f"WHOCC snapshot count says {declared_total}, but records contains {len(records)}")
    return sorted(records, key=lambda record: (record.level, record.code))


def concept_line(record: WhoRecord) -> dict[str, Any]:
    """Build the complete desired state for one WHOCC classification concept."""
    parent = base.ROOT_ID if record.level == 1 else record.parent
    if parent is None:
        raise ValueError(f"WHOCC record {record.code!r} has no parent")
    return {
        "type": "Concept",
        "id": record.code,
        "owner": base.TARGET_OWNER,
        "owner_type": base.OWNER_TYPE,
        "source": base.TARGET_SOURCE,
        "concept_class": base.concept_class_for(record.level),
        "datatype": base.DATATYPE,
        "retired": False,
        "names": [{
            "name": record.title,
            "locale": "en",
            "locale_preferred": True,
            "name_type": base.NAME_TYPE_FSN,
        }],
        "descriptions": [],
        "extras": {
            "ATC Level": record.level,
            "Is_Drug_Class": "Y" if record.level < 5 else "N",
        },
        "parent_concept_urls": [base.concept_url(parent)],
    }


def _concept_delete_line(resource: dict[str, Any]) -> dict[str, Any]:
    concept_id = _require_text(resource, "id", "export concept")
    concept_class = _require_text(resource, "concept_class", f"export concept {concept_id!r}")
    datatype = _require_text(resource, "datatype", f"export concept {concept_id!r}")
    return {
        "type": "Concept",
        "id": concept_id,
        "owner": base.TARGET_OWNER,
        "owner_type": base.OWNER_TYPE,
        "source": base.TARGET_SOURCE,
        "concept_class": concept_class,
        "datatype": datatype,
        "__action": "DELETE",
    }


def _mapping_delete_line(resource: dict[str, Any]) -> dict[str, Any]:
    mapping_id = _require_text(resource, "id", "export mapping")
    context = f"export mapping {mapping_id!r}"
    line = {
        "type": "Mapping",
        "id": mapping_id,
        "owner": base.TARGET_OWNER,
        "owner_type": base.OWNER_TYPE,
        "source": base.TARGET_SOURCE,
        "map_type": _require_text(resource, "map_type", context),
        "from_concept_url": _require_text(resource, "from_concept_url", context),
        "__action": "DELETE",
    }
    to_concept_url = resource.get("to_concept_url")
    if isinstance(to_concept_url, str) and to_concept_url.strip():
        line["to_concept_url"] = to_concept_url
    return line


def _resources_by_id(resources: object, resource_type: str) -> dict[str, dict[str, Any]]:
    if not isinstance(resources, list):
        raise ValueError(f"export must contain a {resource_type.lower()}s list")
    result: dict[str, dict[str, Any]] = {}
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError(f"export {resource_type.lower()} entry must be an object")
        if item.get("type") != resource_type:
            raise ValueError(f"export entry has type {item.get('type')!r}, expected {resource_type!r}")
        resource_id = _require_text(item, "id", f"export {resource_type.lower()}")
        if resource_id in result:
            raise ValueError(f"export repeats {resource_type} id {resource_id!r}")
        result[resource_id] = item
    return result


def build(snapshot: dict[str, Any], export: dict[str, Any]) -> UpdateResult:
    """Return the deterministic WHOCC-only update for one complete WHOATC export.

    Ordering is intentional: full desired concept records first, mapping retirements next while both
    endpoints still exist, and concept retirements last. ``__action: DELETE`` means retirement in
    OCL's versioned importer rather than a physical delete.
    """
    if not isinstance(export, dict):
        raise ValueError("export must be a JSON object")
    records = records_from_snapshot(snapshot)
    concepts = _resources_by_id(export.get("concepts"), "Concept")
    mappings = _resources_by_id(export.get("mappings"), "Mapping")

    record_ids = {record.code for record in records}
    root = concepts.get(base.ROOT_ID)
    root_line = base.root_line()
    stats = {
        "active_concepts_updated": 0,
        "retired_concepts_reactivated": 0,
        "concepts_created": 0,
        "concepts_retired": 0,
        "active_mappings_retired": 0,
        "already_retired_mappings_ignored": 0,
    }

    if root is None:
        stats["concepts_created"] += 1
    elif root.get("retired"):
        stats["retired_concepts_reactivated"] += 1
    else:
        stats["active_concepts_updated"] += 1

    desired_concepts = [root_line]
    for record in records:
        current = concepts.get(record.code)
        if current is None:
            stats["concepts_created"] += 1
        elif current.get("retired"):
            stats["retired_concepts_reactivated"] += 1
        else:
            stats["active_concepts_updated"] += 1
        desired_concepts.append(concept_line(record))

    mapping_deletes: list[dict[str, Any]] = []
    for mapping_id, mapping in sorted(mappings.items()):
        if mapping.get("retired"):
            stats["already_retired_mappings_ignored"] += 1
        else:
            mapping_deletes.append(_mapping_delete_line(mapping))
            stats["active_mappings_retired"] += 1

    concept_deletes: list[dict[str, Any]] = []
    for concept_id, concept in sorted(concepts.items()):
        if concept_id == base.ROOT_ID or concept_id in record_ids or concept.get("retired"):
            continue
        concept_deletes.append(_concept_delete_line(concept))
        stats["concepts_retired"] += 1

    return UpdateResult(lines=desired_concepts + mapping_deletes + concept_deletes, stats=stats)
