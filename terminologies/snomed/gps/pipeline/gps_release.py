"""Reader for the SNOMED International Global Patient Set (GPS) release ZIP.

The official release is a ZIP containing one TSV concept file, ``Readme.txt``, and an implementation
guide PDF. The TSV is a flat identifier list — it deliberately carries no SNOMED CT hierarchy,
relationships, definitions, mappings, or translations. Each row supplies exactly ConceptID, Active,
FSN, and USPreferredTerm. This reader preserves those four fields and rejects malformed rows rather
than inventing a relationship or semantic interpretation.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_COLUMNS = ("ConceptID", "Active", "FSN", "USPreferredTerm")
MEMBER_RE = re.compile(r"SnomedINTL_GPSRelease_PRODUCTION_(\d{8})T\d{6}Z\.txt$")
LICENSE_MARKER = "Creative Commons Attribution-NoDerivatives 4.0 International Public License"


@dataclass(frozen=True)
class GpsConcept:
    code: str
    active: bool
    fsn: str
    preferred_term: str
    source_row: int


@dataclass
class GpsRelease:
    release_date: str  # YYYY-MM-DD, from the member name
    member: str
    readme: str
    concepts: list[GpsConcept] = field(default_factory=list)
    duplicate_codes: list[str] = field(default_factory=list)

    @property
    def active_count(self) -> int:
        return sum(concept.active for concept in self.concepts)

    @property
    def inactive_count(self) -> int:
        return len(self.concepts) - self.active_count


def _release_from_member(member: str) -> str:
    match = MEMBER_RE.search(Path(member).name)
    if not match:
        raise ValueError(f"GPS concept member has an unexpected name: {member!r}")
    date = match.group(1)
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def read(path: Path) -> GpsRelease:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"GPS release ZIP not found: {path}")
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if MEMBER_RE.search(Path(name).name)]
        if len(members) != 1:
            raise ValueError(f"{path}: expected exactly one GPS TSV member, found {members!r}")
        member = members[0]
        try:
            readme = archive.read("Readme.txt").decode("utf-8-sig")
        except KeyError:
            raise ValueError(f"{path}: missing Readme.txt") from None
        if LICENSE_MARKER not in readme:
            raise ValueError(f"{path}: Readme.txt does not state the expected CC BY-ND 4.0 licence")
        release = GpsRelease(release_date=_release_from_member(member), member=member, readme=readme)
        seen: set[str] = set()
        with archive.open(member) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), delimiter="\t")
            if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
                raise ValueError(f"{path}: expected columns {REQUIRED_COLUMNS}, got {reader.fieldnames!r}")
            for number, row in enumerate(reader, start=2):
                code = (row.get("ConceptID") or "").strip()
                active = (row.get("Active") or "").strip()
                fsn = (row.get("FSN") or "").strip()
                preferred_term = (row.get("USPreferredTerm") or "").strip()
                if not code.isdigit() or not code:
                    raise ValueError(f"{path} row {number}: invalid ConceptID {code!r}")
                if active not in {"0", "1"}:
                    raise ValueError(f"{path} row {number}: Active must be '0' or '1', got {active!r}")
                if not fsn or not preferred_term:
                    raise ValueError(f"{path} row {number}: FSN and USPreferredTerm are required")
                if code in seen:
                    release.duplicate_codes.append(code)
                seen.add(code)
                release.concepts.append(GpsConcept(code, active == "1", fsn, preferred_term, number))
    return release
