"""ICD-10 canonical extraction, national-edition name alignment, and OCL bulk-import build.

The package reads a canonical ICD-10 release plus one adapter per national edition
(DATASUS for ``pt_BR``, ATIH for ``fr``), aligns names by exact code, and writes
versionable bulk-import NDJSON parts with a machine-readable audit. It performs no OCL
write and no concept creation, and it never changes hierarchy.
"""

from .canonical import CanonicalConcept, CanonicalIndex, load_baseline
from .model import AdapterResult, NameCandidate

__all__ = [
    "AdapterResult",
    "CanonicalConcept",
    "CanonicalIndex",
    "NameCandidate",
    "load_baseline",
]
