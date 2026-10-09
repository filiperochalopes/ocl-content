"""CLI end-to-end, asset verification, and the read-only hydration guard rails."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from pipeline import assets as asset_registry
from pipeline import hydrate
from pipeline.cli import main


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
    assert audit["alignment"]["exclusions_file"] == str(exclusions)
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


def test_hydrated_run_marks_the_artifacts_as_upload_ready(tmp_path, baseline_csv, datasus_dir, atih_xml, monkeypatch):
    monkeypatch.setenv("OCL_API_TOKEN", "not-a-real-token")

    def fake_hydrate(api_url, owner, source, codes, token, allow_insecure_localhost=False):
        resources = {
            code: {
                "id": code,
                "concept_class": "Code",
                "names": [{"name": "Live English name", "locale": "en", "locale_preferred": True}],
                "descriptions": [],
                "extras": {"hierarchy_level": "3"},
            }
            for code in codes
        }
        return resources, []

    monkeypatch.setattr("pipeline.cli.hydrate", fake_hydrate)
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--hydrate")) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["mode"] == "hydrated-head"
    assert audit["upload_ready"] is True
    assert audit["warning"] is None
    assert audit["hydration"] == {
        "requested": audit["hydration"]["requested"],
        "retrieved": audit["hydration"]["requested"],
        "failures": [],
        "api_url": "https://api.openconceptlab.org",
    }
    first = json.loads((tmp_path / "output" / "bulkimport_part_001.ndjson").read_text(encoding="utf-8").split("\n")[0])
    assert first["names"][0]["name"] == "Live English name"


def test_hydration_failure_aborts_before_writing(tmp_path, baseline_csv, datasus_dir, atih_xml, monkeypatch):
    monkeypatch.setenv("OCL_API_TOKEN", "not-a-real-token")

    def fake_hydrate(api_url, owner, source, codes, token, allow_insecure_localhost=False):
        return {code: {} for code in codes[:0]}, [{"code": code, "error": "GET failed with HTTP 500"} for code in codes]

    monkeypatch.setattr("pipeline.cli.hydrate", fake_hydrate)
    assert main(build_args(tmp_path, baseline_csv, datasus_dir, atih_xml, "--hydrate")) == 1
    assert not (tmp_path / "output").exists()


def test_asset_verification_rejects_a_wrong_hash(tmp_path):
    asset = asset_registry.resolve("datasus-csv")
    path = tmp_path / "CID10CSV.zip"
    path.write_bytes(b"not the pinned file")
    with pytest.raises(ValueError, match="does not match the pinned SHA-256"):
        asset_registry.verify(path, asset)


def test_unknown_asset_key_is_rejected():
    with pytest.raises(KeyError, match="unknown asset"):
        asset_registry.resolve("nope")


def test_hydration_refuses_to_send_a_token_over_plain_http():
    with pytest.raises(ValueError, match="https origin is required"):
        hydrate.fetch_concept("http://api.example.org", "WHO", "ICD-10-WHO", "A00", "token")


def test_hydration_requires_a_token():
    with pytest.raises(ValueError, match="a token is required"):
        hydrate.fetch_concept("https://api.openconceptlab.org", "WHO", "ICD-10-WHO", "A00", "")


def test_hydration_url_encodes_each_segment():
    url = hydrate.concept_url("https://api.openconceptlab.org", "WHO", "ICD-10-WHO", "A00.0")
    assert url == "https://api.openconceptlab.org/orgs/WHO/sources/ICD-10-WHO/concepts/A00.0/"
    with pytest.raises(ValueError, match="not a valid OCL mnemonic"):
        hydrate.concept_url("https://api.openconceptlab.org", "WHO", "ICD-10-WHO", "../../etc/passwd")


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
