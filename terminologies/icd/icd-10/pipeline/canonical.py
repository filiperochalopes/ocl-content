"""The canonical ICD-10 baseline: concept IDs, English names, and attributes to update.

The baseline is the reviewed OCL load artifact recorded in
``terminologies/icd/icd-10/README.md``. It fixes the concept IDs and hierarchy the name
pipeline must not change; the pipeline never derives structure from a national edition.
Its SHA-256 is recorded in every audit so a name proposal always names the snapshot it was
aligned against.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ocl_artifacts import sha256_file  # noqa: F401 - re-exported for the CLI

ATTR_PREFIX = "attr:"


@dataclass(frozen=True)
class CanonicalConcept:
    id: str
    concept_class: str
    name: str
    description: str
    extras: dict[str, str]
    parent_concept_urls: str


@dataclass
class CanonicalIndex:
    path: Path
    sha256: str
    concepts: dict[str, CanonicalConcept] = field(default_factory=dict)

    @property
    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for concept in self.concepts.values():
            counts[concept.concept_class] = counts.get(concept.concept_class, 0) + 1
        return dict(sorted(counts.items()))

    def __contains__(self, code: object) -> bool:
        return code in self.concepts

    def __len__(self) -> int:
        return len(self.concepts)


def load_baseline(path: Path) -> CanonicalIndex:
    """Read the canonical CSV, keeping only non-empty ``attr:`` values as extras."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"canonical baseline not found: {path}")
    index = CanonicalIndex(path=path, sha256=sha256_file(path))
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "id" not in reader.fieldnames or "name" not in reader.fieldnames:
            raise ValueError(f"{path}: expected a CSV with 'id' and 'name' columns")
        for row_number, row in enumerate(reader, start=2):
            concept_id = (row.get("id") or "").strip()
            if not concept_id:
                raise ValueError(f"{path} line {row_number}: blank concept id")
            if concept_id in index.concepts:
                raise ValueError(f"{path} line {row_number}: duplicate concept id {concept_id}")
            extras = {
                key[len(ATTR_PREFIX):]: value.strip()
                for key, value in row.items()
                if key and key.startswith(ATTR_PREFIX) and (value or "").strip()
            }
            index.concepts[concept_id] = CanonicalConcept(
                id=concept_id,
                concept_class=(row.get("concept_class") or "").strip(),
                name=(row.get("name") or "").strip(),
                description=(row.get("description") or "").strip(),
                extras=extras,
                parent_concept_urls=(row.get("parent_concept_urls") or "").strip(),
            )
    return index


def concept_record(concept: CanonicalConcept) -> dict:
    return {
        "id": concept.id,
        "concept_class": concept.concept_class,
        "name": concept.name,
        "description": concept.description,
        "extras": dict(concept.extras),
        "parent_concept_urls": concept.parent_concept_urls,
    }


def write_canonical_jsonl(concepts: list[CanonicalConcept], path: Path) -> Path:
    """Write the extracted canonical structure as JSONL, one concept per line."""
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for concept in concepts:
            stream.write(json.dumps(concept_record(concept), ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def load_canonical_jsonl(path: Path) -> CanonicalIndex:
    """Read a JSONL canonical structure (for example the WHO ClaML extraction)."""
    import json

    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"canonical JSONL not found: {path}")
    index = CanonicalIndex(path=path, sha256=sha256_file(path))
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            concept_id = str(record.get("id") or "").strip()
            if not concept_id:
                raise ValueError(f"{path} line {line_number}: blank concept id")
            if concept_id in index.concepts:
                raise ValueError(f"{path} line {line_number}: duplicate concept id {concept_id}")
            index.concepts[concept_id] = CanonicalConcept(
                id=concept_id,
                concept_class=str(record.get("concept_class") or "").strip(),
                name=str(record.get("name") or "").strip(),
                description=str(record.get("description") or "").strip(),
                extras={str(key): str(value) for key, value in (record.get("extras") or {}).items()},
                parent_concept_urls=str(record.get("parent_concept_urls") or "").strip(),
            )
    return index


def load_canonical(path: Path) -> CanonicalIndex:
    """Load a canonical baseline from a CSV or a JSONL extraction, chosen by suffix."""
    path = Path(path)
    if path.suffix.lower() in (".jsonl", ".json"):
        return load_canonical_jsonl(path)
    return load_baseline(path)
