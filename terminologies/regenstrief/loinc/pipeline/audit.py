"""Read-only audit of LOINC Brazilian Portuguese names against an OCL export."""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

CSV_MEMBER = "AccessoryFiles/LinguisticVariants/ptBR11LinguisticVariant.csv"
PART_FIELDS = (
    "COMPONENT",
    "PROPERTY",
    "TIME_ASPCT",
    "SYSTEM",
    "SCALE_TYP",
    "METHOD_TYP",
    "CLASS",
)
NAME_FIELDS = {
    "fully_specified": ("Fully-Specified", "assembled"),
    "short": ("Short", "SHORTNAME"),
    "related": ("Related", "RELATEDNAMES2"),
}
EXPECTED_OWNER = "Regenstrief"
EXPECTED_SOURCE = "LOINC"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_release(path: Path) -> tuple[list[dict[str, str]], dict[str, str], str]:
    if not path.is_file():
        raise FileNotFoundError(f"LOINC release ZIP not found: {path}")
    with zipfile.ZipFile(path) as archive:
        if CSV_MEMBER not in archive.namelist():
            raise ValueError(f"{path}: missing official file {CSV_MEMBER}")
        raw = archive.read(CSV_MEMBER)
        with archive.open(CSV_MEMBER) as stream:
            import io

            text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            if not reader.fieldnames or "LOINC_NUM" not in reader.fieldnames:
                raise ValueError(f"{CSV_MEMBER}: missing LOINC_NUM column")
            required = set(PART_FIELDS) | {"SHORTNAME", "RELATEDNAMES2"}
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise ValueError(f"{CSV_MEMBER}: missing required columns: {missing}")
            rows = list(reader)
            columns = {name: "present" for name in reader.fieldnames}
    ids = [row["LOINC_NUM"].strip() for row in rows]
    if any(not code for code in ids):
        raise ValueError(f"{CSV_MEMBER}: one or more rows have an empty LOINC_NUM")
    duplicates = sorted(code for code, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"{CSV_MEMBER}: duplicate LOINC_NUM values, e.g. {duplicates[:5]}")
    return rows, columns, _sha256_bytes(raw)


def _load_export(path: Path, expected_version: str) -> tuple[dict[str, dict], dict]:
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise ValueError("OCL input must be the ZIP produced by ocl_export_download.py")
    sidecar_path = path.with_name(path.name + ".provenance.json")
    if not sidecar_path.is_file():
        raise ValueError(f"missing OCL export provenance sidecar: {sidecar_path}")
    provenance = json.loads(sidecar_path.read_text(encoding="utf-8"))
    actual_hash = sha256_path(path)
    if provenance.get("sha256") != actual_hash:
        raise ValueError("OCL export SHA-256 does not match its provenance sidecar")
    if (provenance.get("owner"), provenance.get("source"), provenance.get("version")) != (
        EXPECTED_OWNER,
        EXPECTED_SOURCE,
        expected_version,
    ):
        raise ValueError("OCL export provenance must identify Regenstrief/LOINC/" + expected_version)
    with zipfile.ZipFile(path) as archive:
        if "export.json" not in archive.namelist():
            raise ValueError("OCL ZIP must contain export.json")
        document = json.loads(archive.read("export.json"))
    if not isinstance(document, dict) or not isinstance(document.get("concepts"), list):
        raise ValueError("OCL export must be a Source export with a concepts list")
    if document.get("owner") != EXPECTED_OWNER or document.get("short_code") != EXPECTED_SOURCE:
        raise ValueError("OCL export is not Regenstrief/LOINC")
    if str(document.get("id")) != expected_version or str(document.get("version")) != expected_version:
        raise ValueError(f"OCL export is version {document.get('id')!r}, expected {expected_version!r}")
    concepts: dict[str, dict] = {}
    for concept in document["concepts"]:
        if concept.get("concept_class") != "LOINC":
            continue
        code = str(concept.get("id") or "")
        if code in concepts:
            raise ValueError(f"duplicate LOINC-class concept id in OCL export: {code}")
        concepts[code] = concept
    metadata = {
        "path": str(path),
        "sha256": actual_hash,
        "bytes": path.stat().st_size,
        "api_origin": provenance.get("api_origin"),
        "retrieved_at": provenance.get("retrieved_at"),
        "owner": EXPECTED_OWNER,
        "source": EXPECTED_SOURCE,
        "version": expected_version,
        "concept_records_in_export": len(document["concepts"]),
        "loinc_class_concepts": len(concepts),
        "active_loinc_class_concepts": sum(not bool(c.get("retired")) for c in concepts.values()),
    }
    return concepts, metadata


def _names(concept: dict | None, locale: str, name_type: str) -> list[str]:
    if not concept:
        return []
    return [
        str(item.get("name", ""))
        for item in concept.get("names", [])
        if item.get("locale") == locale
        and item.get("name_type") == name_type
        and not item.get("retired")
        and item.get("name")
    ]


def _comparison(expected: str, candidates: list[str], *, supplied: bool) -> str:
    if not supplied:
        return "not-provided-by-release"
    if expected in candidates:
        return "exact-match"
    if not candidates:
        return "missing-in-ocl"
    return "different-from-ocl"


def run_audit(release_path: Path, export_path: Path, output_dir: Path, version: str) -> dict:
    """Write a JSON summary and row-level CSV; never makes network calls or writes to OCL."""
    rows, release_columns, csv_hash = _load_release(Path(release_path))
    concepts, export_meta = _load_export(Path(export_path), version)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"ptbr_translation_alignment_{version}.csv"
    summary_path = output_dir / f"ptbr_translation_audit_{version}.json"
    field_counts: dict[str, Counter] = {key: Counter() for key in NAME_FIELDS}
    concept_counts: Counter = Counter()

    with detail_path.open("w", encoding="utf-8", newline="") as stream:
        fieldnames = [
            "LOINC_NUM",
            "concept_status",
            "ocl_retired",
            "field",
            "release_value",
            "ocl_values",
            "result",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            code = row["LOINC_NUM"].strip()
            concept = concepts.get(code)
            concept_status = "found" if concept else "missing-in-ocl"
            concept_counts[concept_status] += 1
            retired = bool(concept and concept.get("retired"))
            for field_key, (ocl_type, release_column) in NAME_FIELDS.items():
                if release_column == "assembled":
                    expected = ":".join(row[field].strip() for field in PART_FIELDS if row[field].strip())
                    supplied = bool(expected)
                else:
                    expected = row[release_column].strip()
                    supplied = bool(expected)
                candidates = _names(concept, "pt-BR", ocl_type)
                result = _comparison(expected, candidates, supplied=supplied)
                field_counts[field_key][result] += 1
                writer.writerow(
                    {
                        "LOINC_NUM": code,
                        "concept_status": concept_status,
                        "ocl_retired": str(retired).lower() if concept else "",
                        "field": field_key,
                        "release_value": expected,
                        "ocl_values": " || ".join(candidates),
                        "result": result,
                    }
                )

    summary = {
        "schema_version": 1,
        "audit_type": "read-only-loinc-pt-BR-translation-comparison",
        "scope": "LOINC_NUM records and pt-BR Fully-Specified, Short, and Related names only; exact string comparison",
        "decision_limit": "This is data-presence and exact-label comparison evidence, not a clinical equivalence or translation-quality judgment.",
        "release": {
            "declared_version": version,
            "archive_path": str(Path(release_path).resolve()),
            "archive_sha256": sha256_path(Path(release_path)),
            "linguistic_variant_member": CSV_MEMBER,
            "linguistic_variant_sha256": csv_hash,
            "linguistic_variant_rows": len(rows),
            "columns": list(release_columns),
            "consumer_name_column_present": "ConsumerName" in release_columns,
        },
        "ocl_export": export_meta,
        "counts": {
            "release_rows": len(rows),
            "unique_loinc_codes": len(rows),
            "concepts": dict(sorted(concept_counts.items())),
            "fields": {key: dict(sorted(counts.items())) for key, counts in field_counts.items()},
        },
        "outputs": {"summary": summary_path.name, "details": detail_path.name},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
