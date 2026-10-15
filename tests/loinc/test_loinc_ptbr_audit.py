from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ocl_pipeline_loader import load

audit = load("regenstrief/loinc", "audit")


def make_release(path: Path) -> None:
    content = (
        '"LOINC_NUM","COMPONENT","PROPERTY","TIME_ASPCT","SYSTEM","SCALE_TYP","METHOD_TYP","CLASS",'
        '"SHORTNAME","LONG_COMMON_NAME","RELATEDNAMES2","LinguisticVariantDisplayName"\n'
        '"1234-5","Hemoglobina","Massa","Pt","Sangue","Qn","","CHEM","Hb","","Hb; sangue",""\n'
        '"2345-6","Glicose","Massa","Pt","Soro","Qn","","CHEM","Glic","","",""\n'
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(audit.CSV_MEMBER, content)


def make_export(path: Path) -> None:
    doc = {
        "type": "Source Version",
        "id": "2.82",
        "version": "2.82",
        "owner": "Regenstrief",
        "short_code": "LOINC",
        "concepts": [
            {
                "id": "1234-5",
                "concept_class": "LOINC",
                "retired": False,
                "names": [
                    {"locale": "pt-BR", "name_type": "Fully-Specified", "name": "Hemoglobina:Massa:Pt:Sangue:Qn:CHEM", "retired": False},
                    {"locale": "pt-BR", "name_type": "Short", "name": "Hb", "retired": False},
                    {"locale": "pt-BR", "name_type": "Related", "name": "Hb; sangue", "retired": False},
                ],
            },
            {
                "id": "2345-6",
                "concept_class": "LOINC",
                "retired": True,
                "names": [{"locale": "pt-BR", "name_type": "Fully-Specified", "name": "Old label", "retired": False}],
            },
            {"id": "1234-5", "concept_class": "LOINC Part", "names": []},
        ],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export.json", json.dumps(doc))
    provenance = {
        "api_origin": "https://api.staging.openconceptlab.org",
        "owner": "Regenstrief",
        "source": "LOINC",
        "version": "2.82",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "retrieved_at": "2026-10-15T00:00:00Z",
    }
    path.with_name(path.name + ".provenance.json").write_text(json.dumps(provenance))


def test_audit_compares_release_labels_exactly_and_marks_missing_fields(tmp_path: Path) -> None:
    release = tmp_path / "release.zip"
    export = tmp_path / "export.zip"
    output = tmp_path / "output"
    make_release(release)
    make_export(export)

    summary = audit.run_audit(release, export, output, "2.82")

    assert summary["counts"]["release_rows"] == 2
    assert summary["counts"]["concepts"] == {"found": 2}
    assert summary["counts"]["fields"]["fully_specified"] == {
        "different-from-ocl": 1,
        "exact-match": 1,
    }
    assert summary["counts"]["fields"]["short"] == {
        "exact-match": 1,
        "missing-in-ocl": 1,
    }
    with (output / "ptbr_translation_alignment_2.82.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    assert len(records) == 6
    assert records[0]["result"] == "exact-match"
    assert records[3]["result"] == "different-from-ocl"
    assert json.loads((output / "ptbr_translation_audit_2.82.json").read_text())["ocl_export"]["sha256"] == hashlib.sha256(export.read_bytes()).hexdigest()


def test_audit_refuses_export_with_unmatched_provenance_hash(tmp_path: Path) -> None:
    release = tmp_path / "release.zip"
    export = tmp_path / "export.zip"
    make_release(release)
    make_export(export)
    sidecar = export.with_name(export.name + ".provenance.json")
    provenance = json.loads(sidecar.read_text())
    provenance["sha256"] = "0" * 64
    sidecar.write_text(json.dumps(provenance))

    try:
        audit.run_audit(release, export, tmp_path / "output", "2.82")
    except ValueError as error:
        assert "SHA-256" in str(error)
    else:
        raise AssertionError("expected mismatched export provenance to be rejected")
