"""Pinned FY27 CMS/NCHS ICD-10-CM inputs; public files are manually downloaded/verified here."""

from __future__ import annotations

from pathlib import Path

from ocl_assets import Asset, verify

BASE = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2027/"
TABULAR = Asset("fy27-tabular", "icd10cm-table-and-index-2027.zip", BASE + "icd10cm-table-and-index-2027.zip", "99b5c2be16ff53eab861cc0be4b1dacba27f687b8ff4bc700679944355037ee0", "CDC/NCHS", "ICD-10-CM FY27, October 1 2026", "en", "ZIP with Tabular XML", "cdc/2027/icd10cm-table-and-index-2027.zip")
ORDER = Asset("fy27-order", "icd10cm-code-descriptions-2027.zip", BASE + "icd10cm-code-descriptions-2027.zip", "93e3ad6004badf470c55bfe679b748ae88fd9b2b421851e409eec382c7713b9a", "CDC/NCHS", "ICD-10-CM FY27, October 1 2026", "en", "ZIP with full order file", "cdc/2027/icd10cm-code-descriptions-2027.zip")


def tabular_path(assets_dir: Path) -> Path:
    return Path(assets_dir) / TABULAR.destination


def order_path(assets_dir: Path) -> Path:
    return Path(assets_dir) / ORDER.destination


def verify_local(tabular: Path, order: Path) -> None:
    verify(Path(tabular), TABULAR)
    verify(Path(order), ORDER)
