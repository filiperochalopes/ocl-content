"""Offline rehearsal of the update flow: export -> build --export -> apply -> verify.

This is NOT evidence about a real OCL server. It proves that the three tools agree with each other
and with the documented importer semantics (a bulk update is not a PATCH: it replaces ``names``,
``descriptions`` and ``extras`` of each targeted concept and leaves everything else alone). The
real evidence comes from running the same flow against a local OCL instance (tests/README.md).
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest

from ocl_pipeline_loader import load
import ocl_verify_update

main = load("who/icd-10", "cli").main


def args(tmp_path, baseline_csv, datasus_dir, atih_xml, *extra):
    return ["build", "--baseline", str(baseline_csv), "--datasus", str(datasus_dir), "--atih", str(atih_xml),
            "--output-dir", str(tmp_path / "output"), *extra]


def read_bundle(tmp_path) -> list[dict]:
    text = (tmp_path / "output" / "bulkimport_bundle.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def simulate_import(before: dict[str, dict], artifact: list[dict]) -> dict[str, dict]:
    """The documented importer semantics: replace names/descriptions/extras of the targeted concepts."""
    after = copy.deepcopy(before)
    for line in artifact:
        target = after[line["id"]]
        target["names"], target["descriptions"], target["extras"] = (
            copy.deepcopy(line["names"]), copy.deepcopy(line["descriptions"]), copy.deepcopy(line["extras"]),
        )
    return after


def write_export(path: Path, concepts: dict[str, dict]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export.json", json.dumps({"type": "Source Version", "concepts": list(concepts.values())}))
    return path


@pytest.fixture
def rehearsal(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(args(tmp_path / "probe", baseline_csv, datasus_dir, atih_xml)) == 0
    codes = [line["id"] for line in read_bundle(tmp_path / "probe")]
    before = {
        code: {"type": "Concept", "id": code, "owner": "WHO", "source": "ICD-10-WHO", "concept_class": "Code",
               "retired": False,
               "names": [{"name": f"Live English name of {code}", "locale": "en", "locale_preferred": True,
                          "name_type": "Fully Specified", "uuid": "server-only"}],
               "descriptions": [], "extras": {"hierarchy_level": "3", "chapter_number": "1"}}
        for code in codes
    }
    before["ICD-10"] = {"type": "Concept", "id": "ICD-10", "owner": "WHO", "source": "ICD-10-WHO",
                        "concept_class": "Root", "retired": False,
                        "names": [{"name": "ICD-10 Root Concept", "locale": "en", "locale_preferred": True}],
                        "descriptions": [], "extras": {}}
    export = write_export(tmp_path / "before.zip", before)
    assert main(args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--export", str(export))) == 0
    return tmp_path, before, export, read_bundle(tmp_path)


def verify_args(tmp_path, before_zip, after_zip):
    return ["--before", str(before_zip), "--after", str(after_zip),
            "--artifact", str(tmp_path / "output" / "bulkimport_icd10-who.bundle.zip"),
            "--audit", str(tmp_path / "output" / "bulkimport_audit.json")]


def test_the_whole_flow_agrees_with_itself(rehearsal, capsys):
    tmp_path, before, export, artifact = rehearsal
    after = write_export(tmp_path / "after.zip", simulate_import(before, artifact))
    code = ocl_verify_update.main([*verify_args(tmp_path, export, after), "--report", str(tmp_path / "report.json")])
    assert code == 0, capsys.readouterr().out
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["result"] == "pass"
    assert next(c for c in report["checks"] if c["id"] == "untouched-concepts-identical")["info"]["checked"] >= 1


def test_the_audit_ties_the_artifact_to_the_export_it_was_built_from(rehearsal):
    tmp_path, before, export, _ = rehearsal
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["mode"] == "source-export" and audit["upload_ready"] is True
    assert audit["export"]["sha256"] == __import__("ocl_export").sha256_path(export)


def test_a_collateral_edit_by_the_server_or_a_wrong_upload_is_caught(rehearsal):
    tmp_path, before, export, artifact = rehearsal
    after_concepts = simulate_import(before, artifact)
    after_concepts["ICD-10"]["names"].append({"name": "Raiz", "locale": "pt_BR", "locale_preferred": True,
                                              "name_type": "Fully Specified"})
    after = write_export(tmp_path / "after.zip", after_concepts)
    assert ocl_verify_update.main(verify_args(tmp_path, export, after)) == 1


def test_an_upload_that_dropped_the_live_names_is_caught(rehearsal):
    """What an artifact built from the 2021 baseline would do to a live concept that carries more."""
    tmp_path, before, export, artifact = rehearsal
    after_concepts = simulate_import(before, artifact)
    victim = artifact[0]["id"]
    after_concepts[victim]["names"] = [n for n in after_concepts[victim]["names"] if n["locale"] != "en"]
    after = write_export(tmp_path / "after.zip", after_concepts)
    assert ocl_verify_update.main(verify_args(tmp_path, export, after)) == 1


def test_a_stale_export_is_caught_by_the_audit_hash(rehearsal):
    tmp_path, before, _export, artifact = rehearsal
    newer = copy.deepcopy(before)
    newer["ICD-10"]["names"][0]["name"] = "changed in OCL after the snapshot"
    newer_zip = write_export(tmp_path / "newer.zip", newer)
    after = write_export(tmp_path / "after.zip", simulate_import(newer, artifact))
    assert ocl_verify_update.main(verify_args(tmp_path, newer_zip, after)) == 1
