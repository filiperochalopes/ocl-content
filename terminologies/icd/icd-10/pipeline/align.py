"""Align national-edition name candidates to the canonical ICD-10 codes.

Alignment is code-level only. A candidate is accepted when its code exists in the canonical
release and its label differs from the canonical English name; everything else is reported with
a reason. Two rows proposing different labels for the same code and locale are a conflict and
are refused as a group, because choosing between them is a terminology decision, not a pipeline
decision. Lexical similarity is never used: a code match says nothing about clinical meaning, so
the labels of codes that exist only in a national edition stay out of scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .canonical import CanonicalIndex
from .model import AdapterResult, NameCandidate

ACCEPTED = "accepted"
NOT_IN_CANONICAL = "not-in-canonical"
UNCHANGED = "unchanged"
DUPLICATE_CONFLICT = "duplicate-conflict"
EXCLUDED_BY_CURATOR = "excluded-by-curator"

_WHITESPACE = re.compile(r"\s+")


def comparison_text(text: str) -> str:
    """Comparison-only normalization; the stored label is never modified."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


@dataclass(frozen=True)
class Decision:
    candidate: NameCandidate
    status: str
    reasons: tuple[str, ...] = ()


@dataclass
class Alignment:
    decisions: list[Decision] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for decision in self.decisions:
            totals[decision.status] = totals.get(decision.status, 0) + 1
        return dict(sorted(totals.items()))

    def accepted(self) -> list[Decision]:
        return [decision for decision in self.decisions if decision.status == ACCEPTED]

    def by_code(self) -> dict[str, list[Decision]]:
        grouped: dict[str, list[Decision]] = {}
        for decision in self.accepted():
            grouped.setdefault(decision.candidate.code, []).append(decision)
        return grouped


def align(
    results: Iterable[AdapterResult],
    canonical: CanonicalIndex,
    excluded: dict[tuple[str, str], str] | None = None,
) -> Alignment:
    """Align candidates; ``excluded`` holds curator decisions keyed by ``(code, locale)``.

    An exclusion is a recorded terminology decision, not a pipeline heuristic: it is the escape
    hatch for a code whose national label differs in meaning from the canonical entry.
    """
    alignment = Alignment()
    excluded = excluded or {}
    candidates: list[NameCandidate] = [candidate for result in results for candidate in result.candidates]

    conflicts: dict[tuple[str, str], set[str]] = {}
    for candidate in candidates:
        conflicts.setdefault((candidate.code, candidate.locale), set()).add(candidate.label)
    conflicted = {key for key, labels in conflicts.items() if len(labels) > 1}

    for candidate in candidates:
        key = (candidate.code, candidate.locale)
        reasons = list(candidate.flags)
        if key in excluded:
            reasons.append(f"curator-excluded:{excluded[key] or 'no reason recorded'}")
            alignment.decisions.append(Decision(candidate, EXCLUDED_BY_CURATOR, tuple(reasons)))
        elif key in conflicted:
            labels = ", ".join(sorted(conflicts[key]))
            reasons.append(f"conflicting-labels:{labels}")
            alignment.decisions.append(Decision(candidate, DUPLICATE_CONFLICT, tuple(reasons)))
        elif candidate.code not in canonical:
            reasons.append("code-absent-from-canonical-release")
            alignment.decisions.append(Decision(candidate, NOT_IN_CANONICAL, tuple(reasons)))
        elif comparison_text(candidate.label) == comparison_text(canonical.concepts[candidate.code].name):
            reasons.append("label-equals-canonical-english-name")
            alignment.decisions.append(Decision(candidate, UNCHANGED, tuple(reasons)))
        else:
            reasons.append("exact-code-match")
            alignment.decisions.append(Decision(candidate, ACCEPTED, tuple(reasons)))
    return alignment
