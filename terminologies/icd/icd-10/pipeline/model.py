"""Records shared by the adapters, the alignment step, and the bulk-import builder."""

from __future__ import annotations

from dataclasses import dataclass, field

LOCALE_PT_BR = "pt_BR"
LOCALE_FR = "fr"

# Name type given to every translated name the pipeline adds. It is the OCL/NameTypes standard
# value, and the one the live WHO/ICD-10-WHO English names already carry (e.g. A09).
NAME_TYPE_TRANSLATION = "Fully Specified"

# Name/description fields kept on an OCL resource. Everything else (uuid, version_*,
# checksums, display_name, …) is server-side bookkeeping and must not be sent.
NAME_FIELDS = (
    "name",
    "external_id",
    "locale",
    "locale_preferred",
    "name_type",
    "retired",
    "retire_reason",
)
DESCRIPTION_FIELDS = (
    "description",
    "external_id",
    "locale",
    "locale_preferred",
    "description_type",
    "retired",
    "retire_reason",
)


@dataclass(frozen=True)
class NameCandidate:
    """One label proposed by a national edition for an exact canonical code.

    ``code`` is the canonical-alignment code after the adapter's documented, recorded
    normalization. ``source_code`` keeps the value as written in the file, so a reviewer can
    see exactly what was transformed. Nothing else about the label is altered.
    """

    code: str
    locale: str
    label: str
    authority: str
    edition: str
    kind: str
    source_file: str
    source_code: str
    source_row: int
    variant: str | None = None
    flags: tuple[str, ...] = ()


@dataclass
class AdapterResult:
    """Candidates produced by one adapter, plus what it deliberately did not emit."""

    authority: str
    locale: str
    edition: str
    candidates: list[NameCandidate] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def skip(self, reason: str, **detail) -> None:
        self.skipped.append({"reason": reason, **detail})
