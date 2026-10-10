"""Pinned canonical and translation assets for ICD-10: the registry of URLs, editions, and hashes.

The fetch/verify mechanics are shared with the other pipelines (``tools/ocl_assets.py``). Fetched
data files are never committed (see ``terminologies/.gitignore``). DATASUS serves its files over
plain HTTP, which is why the hash — not TLS — is the integrity control for that source.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from ocl_assets import Asset, fetch_asset, verify  # noqa: F401 - verify/Asset are part of this module's API

ASSETS: dict[str, Asset] = {
    "datasus-csv": Asset(
        key="datasus-csv",
        filename="CID10CSV.zip",
        url="http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip",
        sha256="84f23809275575f751255048064bbb244b0de33fd5987ab98df0f98e5f5d2c95",
        authority="DATASUS",
        edition="CID-10 (DATASUS V2008 download page; the XML declares V2007)",
        locale="pt_BR",
        format="semicolon CSV, ISO-8859-1",
        destination="datasus/2008/CID10CSV.zip",
    ),
    "datasus-xml": Asset(
        key="datasus-xml",
        filename="CID10XML.zip",
        url="http://www2.datasus.gov.br/cid10/V2008/downloads/CID10XML.zip",
        sha256="1f2f34076e50a28510aac7d2068003337aa05df1f4969571b46fd0dfa6de1385",
        authority="DATASUS",
        edition="CID-10 (DATASUS V2008 page; root attribute versao=V2007)",
        locale="pt_BR",
        format="DATASUS-specific XML, ISO-8859-1, DTD entities cruz/aster",
        destination="datasus/2008/CID10XML.zip",
    ),
    "who-claml": Asset(
        key="who-claml",
        filename="icd102019en.xml.zip",
        url="https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip",
        sha256="344c571aa9aed3b9ad1c80261b7828c45cfb5fc0b1a5da64aecef354dff5b3d9",
        authority="WHO",
        edition="ICD-10 EN, title declares 2019-covid-expanded (2020-03-22), Identifier icd10_20210322",
        locale="en",
        format="ClaML",
        destination="who/icd102019en/icd102019en.xml.zip",
    ),
    "atih-claml": Asset(
        key="atih-claml",
        filename="cim10fr2024syst_claml_20231215.zip",
        url="https://www.atih.sante.fr/sites/default/files/content/documents/cim10fr2024syst_claml_20231215.zip",
        sha256="6f7b631d2da9f932b85ed7397c7476169c869ba3992c8f862d2c918332a15c55",
        authority="ATIH",
        edition="CIM-10-FR 2024 (2024-01-01)",
        locale="fr",
        format="ClaML with FM/OMS label variants",
        destination="atih/2024/cim10fr2024syst_claml_20231215.zip",
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
