"""CLI end-to-end, asset verification, offline export reading, and artifact reproducibility."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ocl_pipeline_loader import load
asset_registry = load("icd/icd-10", "assets")
source_export = load("icd/icd-10", "export")
main = load("icd/icd-10", "cli").main


def build_args(tmp_path: Path, baseline_csv, datasus_dir, atih_xml, *extra: str) -> list[str]:
    return [
        "build",
        "--baseline", str(baseline_csv),
        "--datasus", str(datasus_dir),
        "--atih", str(atih_xml),
        "--output-dir", str(tmp_path / "output"),
        "--max-part-size", "1kb",
        *extra,
    ]


def _read_parts(output: Path) -> list[dict]:
    return [
        json.loads(line)
        for part in sorted(output.glob("bulkimport_part_*.ndjson"))
        for line in part.read_text(encoding="utf-8").strip().split("\n")
    ]


def test_build_end_to_end_offline_is_marked_as_a_draft(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml)) == 0
    output = tmp_path / "output"
    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["mode"] == "offline-baseline"
    assert audit["upload_ready"] is False
    assert audit["warning"]
    assert audit["target"] == {"owner": "WHO", "source": "ICD-10-WHO", "owner_type": "Organization"}
    assert audit["build"]["changed_concepts"] > 0
    assert audit["alignment"]["counts"]["accepted"] > 0
    assert audit["alignment"]["counts"]["not-in-canonical"] > 0
    assert [part["name"] for part in audit["output"]["parts"]][0] == "bulkimport_part_001.ndjson"
    assert (output / "alignment_report.csv").is_file()

    parts = sorted(output.glob("bulkimport_part_*.ndjson"))
    assert parts
    assert all(part.stat().st_size <= 1024 for part in parts)
    for part in parts:
        for line in part.read_text(encoding="utf-8").strip().split("\n"):
            resource = json.loads(line)
            assert resource["owner"] == "WHO" and resource["source"] == "ICD-10-WHO"
            assert resource["names"][0]["locale"] == "en"


def test_parts_rebuild_the_bundle_and_the_archive_carries_both(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml)) == 0
    output = tmp_path / "output"
    parts = sorted(output.glob("bulkimport_part_*.ndjson"))
    combined = b"".join(part.read_bytes() for part in parts)
    bundle = output / "bulkimport_bundle.ndjson"
    assert combined == bundle.read_bytes()

    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    archive_path = output / audit["output"]["archive"]["name"]
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert names[: len(parts)] == [part.name for part in parts]
        assert names[-2:] == [bundle.name, "bulkimport_manifest.json"]
        assert archive.read(bundle.name) == bundle.read_bytes()
        manifest = json.loads(archive.read("bulkimport_manifest.json"))
    assert manifest["upload"]["mechanism"] == "manual"
    assert manifest["upload"]["order"] == [part.name for part in parts]
    assert manifest["upload_ready"] is False
    assert manifest["bundle"]["sha256"] == audit["output"]["bundle"]["sha256"]
    assert audit["upload"]["api_upload"] is False
    assert audit["output"]["archive"]["sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert audit["output"]["not_versioned"] == [part.name for part in parts] + [bundle.name, "alignment_report.csv"]


def test_archive_can_be_skipped_and_rebuilt_with_compact(tmp_path, baseline_csv, datasus_dir, atih_xml):
    args = build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--no-archive")
    assert main(args) == 0
    output = tmp_path / "output"
    assert not list(output.glob("*.zip"))

    assert main(["compact", "--output-dir", str(output)]) == 0
    archive_path = output / "bulkimport_icd10-who.zip"
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        assert "bulkimport_manifest.json" in archive.namelist()
        assert archive.getinfo("bulkimport_bundle.ndjson").compress_type == zipfile.ZIP_DEFLATED

    assert main(["compact", "--output-dir", str(output), "--zip-method", "lzma"]) == 0
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.getinfo("bulkimport_bundle.ndjson").compress_type == zipfile.ZIP_LZMA


def test_dev_audit_pair_is_written_only_when_requested(tmp_path, baseline_csv, datasus_dir, atih_xml):
    output = tmp_path / "output"
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml)) == 0
    assert not list(output.glob("*.dev.audit.json"))
    assert json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))["dev_audit"] is None

    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--dev-audit")) == 0
    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["dev_audit"]["before"] == "bulkimport_before.dev.audit.json"
    assert audit["dev_audit"]["after"] == "bulkimport_after.dev.audit.json"
    assert audit["dev_audit"]["versioned"] is False
    assert audit["dev_audit"]["concepts"] == audit["build"]["changed_concepts"]
    assert "bulkimport_before.dev.audit.json" in audit["output"]["not_versioned"]
    assert not any(
        name in audit["output"]["versioned"] for name in ("bulkimport_before.dev.audit.json", "bulkimport_after.dev.audit.json")
    )

    before = json.loads((output / audit["dev_audit"]["before"]).read_text(encoding="utf-8"))
    after = json.loads((output / audit["dev_audit"]["after"]).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in before] == [entry["id"] for entry in after]
    # The pair mirrors the uploaded payload: the after array equals the NDJSON lines.
    assert after == _read_parts(output)


def test_build_proposes_both_editions_without_creating_national_extension_codes(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml)) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["build"]["locale_counts"] == {"fr": audit["build"]["locale_counts"]["fr"], "pt_BR": audit["build"]["locale_counts"]["pt_BR"]}
    lines = _read_parts(tmp_path / "output")
    ids = {line["id"] for line in lines}
    assert "U07.1" in ids            # aligned exact code
    assert "U07.10" not in ids       # French national extension stays out of scope
    u071 = next(line for line in lines if line["id"] == "U07.1")
    chosen = {name["locale"]: name["name"] for name in u071["names"]}
    assert chosen["fr"] == "COVID-19, virus identifié"  # OMS variant, not the FM label


def test_missing_translation_input_fails_with_a_fetch_hint(tmp_path, baseline_csv, atih_xml):
    code = main(
        [
            "build",
            "--baseline", str(baseline_csv),
            "--datasus", str(tmp_path / "absent" / "CID10CSV.zip"),
            "--atih", str(atih_xml),
            "--output-dir", str(tmp_path / "output"),
        ]
    )
    assert code == 1
    assert not (tmp_path / "output").exists()


def test_skip_flag_builds_a_single_locale(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--skip", "fr")) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["build"]["locale_counts"] == {"pt_BR": audit["build"]["locale_counts"]["pt_BR"]}
    assert [adapter["locale"] for adapter in audit["adapters"]] == ["pt_BR"]


def test_curated_exclusions_remove_rows_from_the_proposal(tmp_path, baseline_csv, datasus_dir, atih_xml):
    exclusions = tmp_path / "exclusions.csv"
    exclusions.write_text(
        "code,locale,reason\nJ09,pt_BR,national label names avian influenza\nU07.1,fr,pending French wording review\n",
        encoding="utf-8",
    )
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--exclusions", str(exclusions))) == 0
    output = tmp_path / "output"
    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["alignment"]["counts"]["excluded-by-curator"] == 2
    assert audit["alignment"]["exclusions_file"] == "exclusions.csv"  # outside the repo: name only
    lines = [
        json.loads(line)
        for part in sorted(output.glob("bulkimport_part_*.ndjson"))
        for line in part.read_text(encoding="utf-8").strip().split("\n")
    ]
    ids = {line["id"] for line in lines}
    # J09's only candidate was excluded, so the concept is not proposed at all.
    assert "J09" not in ids
    # U07.1 keeps the French label out while the Brazilian one is still proposed.
    u071 = next(line for line in lines if line["id"] == "U07.1")
    assert [name["locale"] for name in u071["names"]] == ["en", "pt_BR"]


def test_missing_exclusions_file_fails_clearly(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--exclusions", str(tmp_path / "nope.csv"))) == 1


def write_export(path: Path, ids: list[str], *, source: str = "ICD-10-WHO", extra: list[dict] | None = None) -> Path:
    concepts = [
        {
            "type": "Concept",
            "id": code,
            "owner": "WHO",
            "source": source,
            "concept_class": "Code",
            "names": [{"name": "Live English name", "locale": "en", "locale_preferred": True, "uuid": "x"}],
            "descriptions": [],
            "extras": {"hierarchy_level": "3"},
        }
        for code in ids
    ]
    path.write_text(json.dumps({"type": "Source Version", "concepts": concepts + (extra or [])}), encoding="utf-8")
    return path


def _accepted_codes(tmp_path, baseline_csv, datasus_dir, atih_xml) -> list[str]:
    assert main(build_args(tmp_path / "probe", baseline_csv, datasus_dir, atih_xml)) == 0
    return sorted({line["id"] for line in _read_parts(tmp_path / "probe" / "output")})


def test_export_run_marks_the_artifacts_as_upload_ready(tmp_path, baseline_csv, datasus_dir, atih_xml):
    codes = _accepted_codes(tmp_path, baseline_csv, datasus_dir, atih_xml)
    export = write_export(tmp_path / "export.json", codes)
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--export", str(export))) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["mode"] == "source-export"
    assert audit["upload_ready"] is True
    assert audit["warning"] is None
    assert audit["export"] == {
        "path": "export.json",
        "sha256": hashlib.sha256(export.read_bytes()).hexdigest(),
        "bytes": export.stat().st_size,
        "requested": len(codes),
        "found": len(codes),
        "missing": [],
    }
    first = json.loads((tmp_path / "output" / "bulkimport_part_001.ndjson").read_text(encoding="utf-8").split("\n")[0])
    assert first["names"][0]["name"] == "Live English name"
    assert "uuid" not in first["names"][0]  # server bookkeeping is never sent back


def test_export_may_be_a_zip_holding_export_json(tmp_path, baseline_csv, datasus_dir, atih_xml):
    codes = _accepted_codes(tmp_path, baseline_csv, datasus_dir, atih_xml)
    export = write_export(tmp_path / "export.json", codes)
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(export, "export.json")
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--export", str(archive))) == 0


def test_export_missing_a_targeted_concept_aborts_before_writing(tmp_path, baseline_csv, datasus_dir, atih_xml):
    export = write_export(tmp_path / "export.json", [])
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--export", str(export))) == 1
    assert not (tmp_path / "output").exists()


def test_export_of_another_source_is_refused(tmp_path):
    export = write_export(tmp_path / "export.json", ["A00"], source="ICD-10-CM")
    with pytest.raises(ValueError, match="expected 'ICD-10-WHO'"):
        source_export.load_concepts(export, "WHO", "ICD-10-WHO")


def test_export_with_a_duplicate_id_is_refused(tmp_path):
    export = write_export(tmp_path / "export.json", ["A00", "A00"])
    with pytest.raises(ValueError, match="appears more than once"):
        source_export.load_concepts(export, "WHO", "ICD-10-WHO")


def test_export_reads_ndjson(tmp_path):
    path = tmp_path / "export.ndjson"
    path.write_text(
        '{"type":"Concept","id":"A00","concept_class":"Code"}\n{"type":"Mapping","id":"m1"}\n', encoding="utf-8"
    )
    assert list(source_export.load_concepts(path, "WHO", "ICD-10-WHO")) == ["A00"]


def test_missing_export_file_fails_clearly(tmp_path, baseline_csv, datasus_dir, atih_xml):
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--export", str(tmp_path / "nope.json"))) == 1
    assert not (tmp_path / "output").exists()


def test_cli_has_no_network_surface():
    source = (Path(source_export.__file__).parent / "cli.py").read_text(encoding="utf-8")
    for marker in ("urllib", "requests", "http.client", "--hydrate", "OCL_API_TOKEN"):
        assert marker not in source


def test_rebuild_is_byte_identical_and_records_no_absolute_paths(tmp_path, baseline_csv, datasus_dir, atih_xml):
    outputs = []
    for run in ("first", "second"):
        run_dir = tmp_path / run
        run_dir.mkdir()
        assert main(build_args(run_dir, baseline_csv, datasus_dir, atih_xml)) == 0
        outputs.append(run_dir / "output")
    for name in ("bulkimport_audit.json", "bulkimport_icd10-who.zip"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
    audit_text = (outputs[0] / "bulkimport_audit.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in audit_text
    assert "/Users/" not in audit_text
    assert "generated_at" not in audit_text
    with zipfile.ZipFile(outputs[0] / "bulkimport_icd10-who.zip") as archive:
        assert "generated_at" not in archive.read("bulkimport_manifest.json").decode("utf-8")


def test_asset_verification_rejects_a_wrong_hash(tmp_path):
    asset = asset_registry.resolve("datasus-csv")
    path = tmp_path / "CID10CSV.zip"
    path.write_bytes(b"not the pinned file")
    with pytest.raises(ValueError, match="does not match the pinned SHA-256"):
        asset_registry.verify(path, asset)


def test_unknown_asset_key_is_rejected():
    with pytest.raises(KeyError, match="unknown asset"):
        asset_registry.resolve("nope")


def test_canonical_subcommand_extracts_verifies_and_writes_jsonl(tmp_path, who_claml_zip, baseline_csv, capsys):
    out = tmp_path / "canonical_who.jsonl"
    code = main(["canonical", "--who-claml", str(who_claml_zip), "--out", str(out), "--compare", str(baseline_csv)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "modifier-derived" in printed
    assert "verify vs" in printed
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").strip().split("\n")]
    assert {record["id"] for record in records} >= {"1", "22", "A00", "E10", "E10.0"}
    assert all(record["extras"] == {} for record in records)


def test_build_accepts_the_datasus_xml_archive(tmp_path, baseline_csv, datasus_xml_zip, atih_xml):
    args = build_args(tmp_path, baseline_csv, tmp_path / "unused-datasus", atih_xml)
    args[args.index("--datasus") + 1] = str(datasus_xml_zip)
    assert main(args) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert [adapter["authority"] for adapter in audit["adapters"]] == ["DATASUS", "ATIH"]
    assert audit["adapters"][0]["stats"]["versions"] == "V2007"
    assert audit["build"]["locale_counts"]["pt_BR"] > 0


def test_build_can_use_the_who_extraction_as_its_canonical_baseline(tmp_path, who_claml_zip, datasus_dir, atih_xml):
    canonical_jsonl = tmp_path / "canonical_who.jsonl"
    assert main(["canonical", "--who-claml", str(who_claml_zip), "--out", str(canonical_jsonl)]) == 0
    args = build_args(tmp_path, canonical_jsonl, datasus_dir, atih_xml)
    assert main(args) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["inputs"][0]["role"] == "canonical-baseline"
    assert audit["inputs"][0]["path"].endswith("canonical_who.jsonl")


def test_unrecognized_datasus_input_fails_clearly(tmp_path, baseline_csv, atih_xml, capsys):
    bogus = tmp_path / "CID10-something.zip"
    with zipfile.ZipFile(bogus, "w") as archive:
        archive.writestr("readme.txt", "nothing")
    args = build_args(tmp_path, baseline_csv, bogus, atih_xml)
    assert main(args) == 1
    assert "unrecognized DATASUS input" in capsys.readouterr().err
