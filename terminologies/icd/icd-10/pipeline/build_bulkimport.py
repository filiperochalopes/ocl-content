"""Build versionable OCL bulk-import NDJSON parts from aligned name candidates.

The Concept bulk importer creates a new version with ``is_patch=False``: an omitted ``names`` or
``descriptions`` collection is replaced by an empty list, and omitted ``extras`` are only
inherited incidentally. Every line therefore carries the complete ``names``, ``descriptions``,
and ``extras`` of the concept it targets, and nothing else. This mirrors the projection used by
the audited CIEL name update in the sibling ``ciel-scripts`` repository, which relies on OCL
preserving omitted scalar values and hierarchy and on an empty ``mappings`` payload being a
no-op, so ``datatype``, ``external_id``, ``retired``, ``parent_concept_urls``, and ``mappings``
are deliberately not sent.

A translation is added only when its locale has no active name on the concept. If the concept
already has an active name in that locale with different text, the pipeline does not overwrite
it: the row is reported as a locale conflict and the concept keeps its current name.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .align import Alignment
from .canonical import CanonicalIndex
from .model import DESCRIPTION_FIELDS, NAME_FIELDS, NameCandidate

TARGET_OWNER = "WHO"
TARGET_SOURCE = "ICD-10-WHO"
OWNER_TYPE = "Organization"
ENGLISH = "en"

ADDED = "added"
ALREADY_PRESENT = "already-present"
LOCALE_CONFLICT = "locale-conflict"
PROPOSED_UPDATE = "PROPOSED_UPDATE"
NO_CHANGE = "NO_CHANGE"
_WHITESPACE = re.compile(r"\s+")


def pick(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: row[field] for field in fields if field in row and row[field] is not None}


def _key(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().casefold()


def is_active(name: dict) -> bool:
    return not name.get("retired")


@dataclass
class ConceptState:
    concept_id: str
    concept_class: str
    names: list[dict] = field(default_factory=list)
    descriptions: list[dict] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_canonical(cls, concept) -> "ConceptState":
        names = (
            [{"name": concept.name, "locale": ENGLISH, "locale_preferred": True, "retired": False}]
            if concept.name
            else []
        )
        descriptions = (
            [{"description": concept.description, "locale": ENGLISH, "locale_preferred": True, "retired": False}]
            if concept.description
            else []
        )
        return cls(
            concept_id=concept.id,
            concept_class=concept.concept_class,
            names=names,
            descriptions=descriptions,
            extras=dict(concept.extras),
        )

    @classmethod
    def from_export(cls, resource: dict) -> "ConceptState":
        """Build the state from an OCL concept resource (a live HEAD GET or an export object)."""
        concept_id = str(resource.get("id") or "")
        if not concept_id:
            raise ValueError("concept resource without an id")
        return cls(
            concept_id=concept_id,
            concept_class=str(resource.get("concept_class") or ""),
            names=[pick(name, NAME_FIELDS) for name in resource.get("names") or [] if isinstance(name, dict)],
            descriptions=[
                pick(description, DESCRIPTION_FIELDS)
                for description in resource.get("descriptions") or []
                if isinstance(description, dict)
            ],
            extras=dict(resource.get("extras") or {}),
        )

    def copy(self) -> "ConceptState":
        return ConceptState(
            concept_id=self.concept_id,
            concept_class=self.concept_class,
            names=[dict(name) for name in self.names],
            descriptions=[dict(description) for description in self.descriptions],
            extras=dict(self.extras),
        )

    def project(self) -> dict:
        """The one projection used for the audit and the NDJSON line."""
        return {
            "type": "Concept",
            "id": self.concept_id,
            "concept_class": self.concept_class,
            "names": [pick(name, NAME_FIELDS) for name in self.names],
            "descriptions": [pick(description, DESCRIPTION_FIELDS) for description in self.descriptions],
            "extras": dict(self.extras),
            "owner": TARGET_OWNER,
            "owner_type": OWNER_TYPE,
            "source": TARGET_SOURCE,
        }


def add_name(state: ConceptState, candidate: NameCandidate) -> tuple[str, str]:
    """Add one candidate name; never modify or demote an existing locale."

    Returns ``(status, detail)``.
    """
    active = [name for name in state.names if is_active(name) and name.get("locale") == candidate.locale]
    for name in active:
        if _key(str(name.get("name") or "")) == _key(candidate.label):
            return ALREADY_PRESENT, "name-already-active-in-locale"
    if active:
        existing = "; ".join(str(name.get("name") or "") for name in active)
        return LOCALE_CONFLICT, f"active-{candidate.locale}-name-not-replaced:{existing}"
    # The locale had no active name, so this becomes the preferred name of that locale.
    state.names.append(
        {
            "name": candidate.label,
            "locale": candidate.locale,
            "locale_preferred": True,
            "retired": False,
        }
    )
    return ADDED, f"added-{candidate.locale}-preferred-name"


@dataclass
class Outcome:
    code: str
    concept_class: str
    status: str
    added: list[dict] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    before_names: int = 0
    after_names: int = 0


@dataclass
class BuildResult:
    lines: list[dict]
    outcomes: list[Outcome]
    before: list[dict]
    after: list[dict]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        return dict(sorted(counts.items()))

    def locale_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            for name in outcome.added:
                counts[name["locale"]] = counts.get(name["locale"], 0) + 1
        return dict(sorted(counts.items()))


def build(
    alignment: Alignment,
    states: dict[str, ConceptState],
) -> BuildResult:
    """Produce one line per concept that actually changes."""
    lines: list[dict] = []
    before_lines: list[dict] = []
    after_lines: list[dict] = []
    outcomes: list[Outcome] = []
    grouped = alignment.by_code()
    for code in sorted(grouped):
        decisions = grouped[code]
        state = states[code].copy()
        before = state.project()
        added: list[dict] = []
        conflicts: list[str] = []
        unchanged: list[str] = []
        for decision in sorted(decisions, key=lambda item: (item.candidate.locale, item.candidate.label)):
            status, detail = add_name(state, decision.candidate)
            if status == ADDED:
                added.append({"locale": decision.candidate.locale, "name": decision.candidate.label, "reason": detail})
            elif status == LOCALE_CONFLICT:
                conflicts.append(f"{decision.candidate.locale}:{detail}")
            else:
                unchanged.append(f"{decision.candidate.locale}:{detail}")
        after = state.project()
        changed = bool(added) and after != before
        outcomes.append(
            Outcome(
                code=code,
                concept_class=state.concept_class,
                status=PROPOSED_UPDATE if changed else NO_CHANGE,
                added=added,
                conflicts=conflicts,
                unchanged=unchanged,
                before_names=len(before["names"]),
                after_names=len(after["names"]),
            )
        )
        if changed:
            before_lines.append(before)
            after_lines.append(after)
            lines.append(after)
    return BuildResult(lines=lines, outcomes=outcomes, before=before_lines, after=after_lines)


@dataclass(frozen=True)
class PartInfo:
    name: str
    lines: int
    sha256: str
    bytes: int


DEFAULT_PART_BYTES = 2 * 1024 * 1024
BUNDLE_NAME = "bulkimport_bundle.ndjson"


def serialize(line: dict) -> bytes:
    return (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _flush(out_dir: Path, stem: str, index: int, chunks: list[bytes]) -> PartInfo:
    payload = b"".join(chunks)
    name = f"{stem}_{index:03d}.ndjson"
    (out_dir / name).write_bytes(payload)
    return PartInfo(name=name, lines=len(chunks), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def write_parts(
    out_dir: Path,
    lines: list[dict],
    max_bytes: int = DEFAULT_PART_BYTES,
    stem: str = "bulkimport_part",
) -> list[PartInfo]:
    """Write ``<stem>_001.ndjson`` (…) parts, each at most ``max_bytes`` of serialized payload.

    Parts are cut on resource boundaries in the input order, so concatenating them in numeric
    order reproduces the bundle exactly. A single resource larger than the limit is an error:
    a resource is never split. Parts from a previous run with the same stem are removed first.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be 1 or more")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{stem}_*.ndjson"):
        stale.unlink()
    parts: list[PartInfo] = []
    chunks: list[bytes] = []
    size = 0
    for line in lines:
        payload = serialize(line)
        if len(payload) > max_bytes:
            raise ValueError(
                f"concept {line.get('id')!r} serializes to {len(payload):,} bytes, above the "
                f"{max_bytes:,}-byte part limit; a resource cannot be split across parts"
            )
        if chunks and size + len(payload) > max_bytes:
            parts.append(_flush(out_dir, stem, len(parts) + 1, chunks))
            chunks, size = [], 0
        chunks.append(payload)
        size += len(payload)
    if chunks:
        parts.append(_flush(out_dir, stem, len(parts) + 1, chunks))
    return parts


def write_bundle(out_dir: Path, lines: list[dict], name: str = BUNDLE_NAME) -> PartInfo:
    """Write the complete bundle: every line, in order, as one NDJSON file."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = b"".join(serialize(line) for line in lines)
    (out_dir / name).write_bytes(payload)
    return PartInfo(name=name, lines=len(lines), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class AuditPairInfo:
    before: str
    after: str
    concepts: int


def write_audit_pair(
    out_dir: Path,
    before: list[dict],
    after: list[dict],
    stem: str = "bulkimport",
) -> AuditPairInfo:
    """Write the pretty-printed before/after pair used to review a proposal as a diff.

    The two arrays carry exactly the same concept IDs, in the same order, with the same
    import-relevant fields, so a JSON diff shows only real changes — the contract the sibling
    ``ciel-scripts`` repository documents as "the canonical audit diff input". The pair is a
    development/review aid: neither file is uploaded, and neither is versioned.
    """
    before_ids = [str(entry.get("id")) for entry in before]
    after_ids = [str(entry.get("id")) for entry in after]
    if before_ids != after_ids:
        raise ValueError(
            "before/after audit arrays must share the same concept IDs in the same order: "
            f"{len(before_ids)} before vs {len(after_ids)} after"
        )
    out_dir = Path(out_dir)
    paths = {}
    for label, entries in (("before", before), ("after", after)):
        path = out_dir / f"{stem}_{label}.dev.audit.json"
        write_json(path, entries)
        paths[label] = path.name
    return AuditPairInfo(before=paths["before"], after=paths["after"], concepts=len(after))


def write_alignment_csv(path: Path, alignment: Alignment) -> None:
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "code", "locale", "status", "label", "authority", "edition", "kind",
        "variant", "flags", "source_file", "source_code", "source_row", "reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for decision in sorted(
            alignment.decisions,
            key=lambda item: (item.status, item.candidate.code, item.candidate.locale, item.candidate.label),
        ):
            candidate = decision.candidate
            writer.writerow(
                {
                    "code": candidate.code,
                    "locale": candidate.locale,
                    "status": decision.status,
                    "label": candidate.label,
                    "authority": candidate.authority,
                    "edition": candidate.edition,
                    "kind": candidate.kind,
                    "variant": candidate.variant or "",
                    "flags": ";".join(candidate.flags),
                    "source_file": candidate.source_file,
                    "source_code": candidate.source_code,
                    "source_row": candidate.source_row,
                    "reasons": ";".join(decision.reasons),
                }
            )
