"""Pinned input for ICD-11: the WHO Simple Tabulation release.

Fetch/verify mechanics are shared with the other pipelines (``tools/ocl_assets.py``). The file is
never committed (see ``terminologies/.gitignore``); the hash is the integrity control.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from ocl_assets import Asset, fetch_asset, verify  # noqa: F401 - verify/Asset are part of this module's API

ASSETS: dict[str, Asset] = {
    "simple-tabulation": Asset(
        key="simple-tabulation",
        filename="SimpleTabulation-ICD-11-MMS-en.zip",
        # The official WHO location of the 2026-01 release, which returns the file hashed below
        # (verified byte-for-byte against the copy kept in the sibling ciel-scripts repository). The
        # 2025-01 path of the same file name serves an older release with a different hash.
        url="https://icdcdn.who.int/static/releasefiles/2026-01/SimpleTabulation-ICD-11-MMS-en.zip",
        sha256="f1356588f40953a83e3af2b662deab47c5e269f944d1ea4ed0cfeb2007c7cd39",
        authority="WHO",
        edition="ICD-11 MMS 2026-01, header 'Version:2026 Jan 17 - 05:30 UTC'",
        locale="en",
        format="tab-separated text (and XLSX) inside a ZIP, UTF-8 with BOM",
        destination="who/2026-01/SimpleTabulation-ICD-11-MMS-en.zip",
    ),
}


def resolve(key: str) -> Asset:
    try:
        return ASSETS[key]
    except KeyError:
        known = ", ".join(sorted(ASSETS))
        raise KeyError(f"unknown asset {key!r}; known assets: {known}") from None


def fetch(
    key: str,
    assets_dir: Path,
    *,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> Path:
    """Download one asset into ``assets_dir`` and verify it before it is kept."""
    return fetch_asset(resolve(key), assets_dir, force=force, opener=opener)
