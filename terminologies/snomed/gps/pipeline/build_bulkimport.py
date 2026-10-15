"""Build the complete flat SNOMED GPS Source from one official release.

The GPS release itself defines all content/lifecycle semantics: `Active=1` becomes an active OCL
concept and `Active=0` becomes a retired OCL concept. No ID is retired merely because it is absent
from a prior OCL Source snapshot; the official GPS package explicitly includes historic inactive
concepts. The output intentionally has no hierarchy, mappings, descriptions, or extras. It projects
the trailing semantic tag from each source FSN as the OCL ``concept_class``; GPS is otherwise a flat
identifier-and-term artifact under CC BY-ND 4.0.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .gps_release import GpsConcept, GpsRelease

TARGET_OWNER = "SNOMED-International"
TARGET_SOURCE = "SNOMED-GPS"
OWNER_TYPE = "Organization"
FSN_SEMANTIC_TAG_RE = re.compile(r"^.+ \((?P<semantic_tag>[^()]+)\)$")


def semantic_tag(fsn: str) -> str:
    """Return the source SNOMED FSN's trailing semantic tag.

    GPS supplies FSNs rather than a separate semantic-tag field. Every row in the pinned January
    2026 release has exactly one non-empty trailing tag, so refusing an unexpected FSN preserves
    that source contract instead of assigning a generic OCL class.
    """
    match = FSN_SEMANTIC_TAG_RE.fullmatch(fsn)
    tag = match.group("semantic_tag").strip() if match else ""
    if not tag:
        raise ValueError(f"GPS FSN lacks one trailing semantic tag: {fsn!r}")
    return tag


def concept_line(concept: GpsConcept) -> dict:
    return {
        "type": "Concept",
        "id": concept.code,
        "owner": TARGET_OWNER,
        "owner_type": OWNER_TYPE,
        "source": TARGET_SOURCE,
        "concept_class": semantic_tag(concept.fsn),
        "datatype": "None",
        "retired": not concept.active,
        "names": [
            {"name": concept.fsn, "locale": "en", "locale_preferred": False, "name_type": "Fully-Specified"},
            {"name": concept.preferred_term, "locale": "en", "locale_preferred": True},
        ],
    }


@dataclass(frozen=True)
class BuildResult:
    lines: list[dict]
    active: int
    retired: int


def build(release: GpsRelease) -> BuildResult:
    if release.duplicate_codes:
        raise ValueError(
            f"{len(release.duplicate_codes)} duplicate ConceptIDs in the GPS release, e.g. {release.duplicate_codes[:5]}"
        )
    lines = [concept_line(concept) for concept in release.concepts]
    return BuildResult(lines=lines, active=release.active_count, retired=release.inactive_count)
