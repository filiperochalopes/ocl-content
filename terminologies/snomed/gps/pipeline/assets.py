"""Pinned manually acquired SNOMED GPS release.

SNOMED International distributes GPS after a web form and email workflow; this pipeline therefore
never tries to download the file. Place the received ZIP at the documented path, then build verifies
its SHA-256 before parsing. The release is licensed CC BY-ND 4.0, so the raw ZIP is Git-ignored.
"""

from __future__ import annotations

from pathlib import Path

from ocl_assets import Asset, verify  # re-exported for consistent asset verification

GPS_2026_01 = Asset(
    key="gps-2026-01",
    filename="SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip",
    url="https://www.snomed.org/gps (form and email distribution; no automated download)",
    sha256="f49909beb10ce0c9897863237730cfc5362d1a8a519d3f69e59121305facec75",
    authority="SNOMED International",
    edition="SNOMED International Global Patient Set, dependent International Edition January 2026 (20260101)",
    locale="en",
    format="ZIP: TSV concept file + Readme.txt + PDF implementation guide",
    destination="snomed/2026-01/SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip",
)


def default_path(assets_dir: Path) -> Path:
    return Path(assets_dir) / GPS_2026_01.destination


def verify_local(path: Path) -> None:
    verify(Path(path), GPS_2026_01)
