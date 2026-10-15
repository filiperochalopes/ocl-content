"""Reader for the flat Foundation-alias CSV (``flat_foundation_synonyms.csv``).

The input is produced by the sibling ``ciel-scripts`` repository's ``list_flat_foundation_synonyms.py``
(read-only reference; nothing here imports it). One row is a Foundation entity that the WHO ICD-API
search index folds into a flat stem or extension code. Its ``evidence`` column is a heuristic of that
script, **not** a proof of synonymy: in the 2026-01 capture every row is ``narrower`` (a more specific
Foundation descendant of the code) or ``residual_rollup`` (rolls up into a ``.Y``/``.Z`` code), and none
has the code's own title.

The owner decided to carry every such title as an *untyped* name of the code (``name_type`` omitted),
so the evidence is preserved here and counted in the audit, but never used to filter or to label the
name as a synonym. The file is generated locally, so it is passed by path at build time and not committed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_COLUMNS = ("code", "foundation_id", "foundation_title", "evidence")


@dataclass(frozen=True)
class FlatAlias:
    name: str
    foundation_id: str
    evidence: str


@dataclass
class FlatAliases:
    by_code: dict[str, list[FlatAlias]] = field(default_factory=dict)
    total_read: int = 0
    skipped: int = 0  # rows without a code or without a name
    duplicate_names: int = 0  # same name (case-insensitive) repeated within one code
    evidence_counts: dict[str, int] = field(default_factory=dict)

    @property
    def names(self) -> int:
        return sum(len(aliases) for aliases in self.by_code.values())


def read(path: Path) -> FlatAliases:
    """Read the CSV into ordered aliases per code; a repeated name within a code is kept once."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"flat Foundation synonyms CSV not found: {path}")
    result = FlatAliases()
    seen: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        for raw in reader:
            result.total_read += 1
            code = (raw.get("code") or "").strip()
            name = (raw.get("foundation_title") or "").strip()
            if not code or not name:
                result.skipped += 1
                continue
            evidence = (raw.get("evidence") or "").strip() or "unknown"
            result.evidence_counts[evidence] = result.evidence_counts.get(evidence, 0) + 1
            key = name.casefold()
            if key in seen.setdefault(code, set()):
                result.duplicate_names += 1
                continue
            seen[code].add(key)
            result.by_code.setdefault(code, []).append(
                FlatAlias(name=name, foundation_id=(raw.get("foundation_id") or "").strip(), evidence=evidence)
            )
    result.evidence_counts = dict(sorted(result.evidence_counts.items()))
    return result
