"""The WHO-ATC build, its artifacts, and the guarantees every pipeline here shares."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from ocl_pipeline_loader import load

ttl_reader = load("who/atc", "ttl_reader")
build = load("who/atc", "build_bulkimport").build
build_module = load("who/atc", "build_bulkimport")
main = load("who/atc", "cli").main


def lines_for(ttl_path):
    return build(ttl_reader.read(ttl_path)).lines


def test_root_comes_first_and_chapters_hang_under_it(ttl_path):
    lines = lines_for(ttl_path)
    assert lines[0]["id"] == "Root" and lines[0]["concept_class"] == "Root"
    assert lines[0]["names"][0]["name"] == "Root"
    chapter = next(line for line in lines if line["id"] == "A")
    assert chapter["concept_class"] == "Chapter"
    assert chapter["parent_concept_urls"] == ["/orgs/WHO/sources/WHOATC/concepts/Root/"]


def test_level_to_class_mapping(ttl_path):
    lines_by_id = {line["id"]: line for line in lines_for(ttl_path) if line["type"] == "Concept"}
    assert lines_by_id["A"]["concept_class"] == "Chapter"
    assert lines_by_id["A01"]["concept_class"] == "Group"
    assert lines_by_id["A01A"]["concept_class"] == "Subgroup"
    assert lines_by_id["A01AD"]["concept_class"] == "Subgroup"
    assert lines_by_id["A01AD02"]["concept_class"] == "Code"


def test_hierarchy_follows_subclassof_chain(ttl_path):
    lines_by_id = {line["id"]: line for line in lines_for(ttl_path) if line["type"] == "Concept"}
    assert lines_by_id["A01"]["parent_concept_urls"] == ["/orgs/WHO/sources/WHOATC/concepts/A/"]
    assert lines_by_id["A01AD02"]["parent_concept_urls"] == ["/orgs/WHO/sources/WHOATC/concepts/A01AD/"]


def test_extras_use_the_documented_keys_and_datatype_is_none(ttl_path):
    lines_by_id = {line["id"]: line for line in lines_for(ttl_path) if line["type"] == "Concept"}
    chapter = lines_by_id["A"]
    assert chapter["datatype"] == "None"
    assert chapter["extras"]["ATC Level"] == "1"
    assert chapter["extras"]["CUI"] == "C3653992"
    assert chapter["extras"]["Is_Drug_Class"] == "Y"
    assert chapter["extras"]["Semantic Types"] == ["T121"]
    leaf = lines_by_id["A01AD02"]
    assert leaf["extras"]["Is_Drug_Class"] == "N"  # derived: absent in the file at level 5


def test_cui_becomes_a_note_description(ttl_path):
    lines_by_id = {line["id"]: line for line in lines_for(ttl_path) if line["type"] == "Concept"}
    assert lines_by_id["A"]["descriptions"] == [
        {"description": "UMLS CUI: C3653992", "locale": "en", "locale_preferred": True, "type": "Note"}
    ]


def test_full_active_build_contains_no_mappings_or_retirements(ttl_path):
    lines = lines_for(ttl_path)
    assert all(line["type"] == "Concept" for line in lines)
    assert all(line["retired"] is False for line in lines)
    assert all(len(line["names"]) == 1 for line in lines)


def test_duplicate_code_is_refused(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    ontology.duplicate_codes.append("A01")
    with pytest.raises(ValueError, match="duplicate"):
        build(ontology)


def test_reserved_root_id_is_refused(ttl_path):
    from dataclasses import replace

    ontology = ttl_reader.read(ttl_path)
    clashing = replace(ontology.classes[0], code="Root")
    ontology.classes.append(clashing)
    with pytest.raises(ValueError, match="reserved root id"):
        build(ontology)


def test_concept_url_escapes_reserved_characters():
    assert build_module.concept_url("A/B&C") == "/orgs/WHO/sources/WHOATC/concepts/A%2FB%26C/"


def build_args(tmp_path: Path, ttl: Path, *extra: str) -> list[str]:
    return [
        "build", "--ttl", str(ttl), "--output-dir", str(tmp_path / "output"), "--max-part-size", "2mb", *extra,
    ]


def test_cli_writes_bundle_archive_and_audit(tmp_path, ttl_path):
    assert main(build_args(tmp_path, ttl_path)) == 0
    output = tmp_path / "output"
    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["target"] == {"owner": "WHO", "source": "WHOATC", "owner_type": "Organization"}
    assert audit["upload_ready"]["local"]["status"] is False
    assert audit["upload"]["mechanism"] == "manual" and audit["upload"]["api_upload"] is False
    assert audit["projection"]["omitted"] == ["Source record", "mappings", "DDD and ATC/DDD Guidelines content"]
    with zipfile.ZipFile(output / "bulkimport_whoatc.bundle.zip") as archive:
        assert archive.namelist() == ["bulkimport_bundle.ndjson"]
    with zipfile.ZipFile(output / "bulkimport_whoatc.parts.zip") as archive:
        assert "bulkimport_manifest.json" in archive.namelist()
        for name in archive.namelist():
            if name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(archive.read(name))) as inner:
                    assert len(inner.namelist()) == 1


def test_rebuild_is_byte_identical(tmp_path, ttl_path):
    outputs = []
    for run in ("first", "second"):
        run_dir = tmp_path / run
        run_dir.mkdir()
        assert main(build_args(run_dir, ttl_path)) == 0
        outputs.append(run_dir / "output")
    for name in ("bulkimport_audit.json", "bulkimport_whoatc.bundle.zip", "bulkimport_bundle.ndjson"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
    text = (outputs[0] / "bulkimport_audit.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "/Users/" not in text


def test_missing_ttl_fails_with_a_fetch_hint(tmp_path):
    assert main(build_args(tmp_path, tmp_path / "absent.ttl")) == 1
    assert not (tmp_path / "output").exists()


def test_the_build_has_no_network_surface():
    source = (
        Path(__file__).resolve().parents[2] / "terminologies/who/atc/pipeline/build_bulkimport.py"
    ).read_text()
    for marker in ("urllib.request", "urlopen", "requests", "http.client", "OCL_API_TOKEN"):
        assert marker not in source
