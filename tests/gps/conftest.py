"""Synthetic GPS release fixtures."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

README = """© 2026 SNOMED International.
Creative Commons Attribution-NoDerivatives 4.0 International Public License
Dependent International Edition version: January 2026 (20260101)
"""
TSV = """ConceptID\tActive\tFSN\tUSPreferredTerm
22298006\t1\tMyocardial infarction (disorder)\tMyocardial infarction
80146002\t0\tExcision of appendix (procedure)\tAppendectomy
"""


@pytest.fixture
def gps_zip(tmp_path) -> Path:
    path = tmp_path / "SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.txt", TSV)
        archive.writestr("Readme.txt", README)
        archive.writestr("guide.pdf", b"not a real PDF")
    return path
