"""tools/ocl_replica_seed.py: export -> Source configuration + ordered, importable bulk-import parts."""

from __future__ import annotations

import json
import zipfile

import pytest

import ocl_replica_seed as subject

BASE = "/orgs/WHO/sources/ICD-10-WHO/concepts"


def concept(cid, parents=(), **extra):
    return {"type": "Concept", "id": cid, "concept_class": "Code", "datatype": "None", "retired": False,
            "uuid": "server-only", "version": "123", "checksums": {"x": 1}, "display_name": cid,
            "names": [{"name": f"Name {cid}", "locale": "en", "locale_preferred": True, "name_type": "Fully Specified",
                       "uuid": "n1", "checksum": "c"}],
            "descriptions": [], "extras": {"hierarchy_level": "3"},
            "parent_concept_urls": list(parents), **extra}


def header(**extra):
    return {"type": "Source Version", "id": "HEAD", "version": "HEAD", "short_code": "ICD-10-WHO", "owner": "WHO",
            "name": "ICD-10, WHO", "full_name": "ICD-10, WHO", "description": "ICD-10 WHO Version", "source_type": "External",
            "default_locale": "en", "supported_locales": ["en"], "public_access": "View",
            "canonical_url": "http://hl7.org/fhir/sid/icd-10", "custom_validation_schema": "None",
            "hierarchy_root_url": f"{BASE}/ICD-10/", "hierarchy_meaning": None, "website": None, "properties": [],
            "filters": [], "extras": {"__export_time": "23.1"}, "uuid": "u", "url": "/x/", "updated_on": "2024-12-04", **extra}


@pytest.fixture
def export():
    # children listed BEFORE their parents, parent URLs carry version ids, B09 has two versions of one parent
    return {**header(), "mappings": [], "references": [], "concepts": [
        concept("A00", [f"{BASE}/A00-A09/900/"]),
        concept("A00-A09", [f"{BASE}/1/901/"]),
        concept("1", [f"{BASE}/ICD-10/902/"]),
        concept("B09", [f"{BASE}/A00-A09/900/", f"{BASE}/A00-A09/565/"]),
        concept("ICD-10", [], concept_class="Root"),
        concept("ORPHAN", []),
    ]}


def lines_of(export):
    return subject.build(export, "WHO", "ICD-10-WHO")


def test_source_create_uses_the_short_code_not_the_version_id(export):
    body = lines_of(export)["source_create"]
    assert body["id"] == "ICD-10-WHO" and body["short_code"] == "ICD-10-WHO"
    assert body["name"] == "ICD-10, WHO" and body["supported_locales"] == ["en"] and body["public_access"] == "View"
    assert body["canonical_url"] == "http://hl7.org/fhir/sid/icd-10"


def test_source_create_keeps_configuration_only(export):
    body = lines_of(export)["source_create"]
    for server_owned in ("uuid", "url", "updated_on", "version", "type", "owner", "hierarchy_root_url", "hierarchy_meaning"):
        assert server_owned not in body
    assert "website" not in body and "properties" not in body and "filters" not in body  # empty values dropped
    assert "extras" not in body  # __export_time is an artifact of generating the export


def test_user_extras_survive_but_export_artifacts_do_not():
    body = subject.source_create_body(header(extras={"__export_time": "9", "owner_note": "keep"}))
    assert body["extras"] == {"owner_note": "keep"}


def test_the_hierarchy_root_waits_until_after_the_import(export):
    assert lines_of(export)["post_import"] == {"hierarchy_root_url": f"{BASE}/ICD-10/"}


def test_no_source_or_organization_line_is_emitted(export):
    assert {line["type"] for line in lines_of(export)["lines"]} == {"Concept"}


def test_concepts_are_shaped_without_server_bookkeeping(export):
    line = next(l for l in lines_of(export)["lines"] if l["id"] == "A00")
    assert set(line) == {"type", "id", "concept_class", "datatype", "names", "extras", "retired", "parent_concept_urls",
                         "owner", "owner_type", "source"}
    assert line["names"] == [{"name": "Name A00", "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}]
    assert line["owner"] == "WHO" and line["source"] == "ICD-10-WHO" and line["owner_type"] == "Organization"


def test_parent_urls_lose_their_version_id_and_duplicates_collapse(export):
    result = lines_of(export)
    by_id = {l["id"]: l for l in result["lines"]}
    assert by_id["A00"]["parent_concept_urls"] == [f"{BASE}/A00-A09/"]
    assert by_id["B09"]["parent_concept_urls"] == [f"{BASE}/A00-A09/"]
    assert result["parent_urls"] == {"unversioned": 5, "concepts_with_duplicate_parents_collapsed": ["B09"]}


def test_every_parent_comes_before_its_children(export):
    result = lines_of(export)
    position = {l["id"]: i for i, l in enumerate(result["lines"])}
    for line in result["lines"]:
        for url in line.get("parent_concept_urls", []):
            assert position[url.rstrip("/").rsplit("/", 1)[1]] < position[line["id"]]
    assert result["ordering"]["concepts_moved"] > 0


def test_concepts_without_a_parent_are_named_not_hidden(export):
    assert lines_of(export)["ordering"]["ids_without_parent"] == ["ICD-10", "ORPHAN"]


def test_a_parent_outside_the_export_is_counted():
    result = subject.build({**header(), "concepts": [concept("A00", [f"{BASE}/MISSING/1/"])]}, "WHO", "ICD-10-WHO")
    assert result["ordering"]["parents_outside_the_set"] == 1


def test_a_hierarchy_cycle_is_refused():
    cyc = {**header(), "concepts": [concept("A", [f"{BASE}/B/1/"]), concept("B", [f"{BASE}/A/1/"])]}
    with pytest.raises(ValueError, match="cycle"):
        subject.build(cyc, "WHO", "ICD-10-WHO")


def test_a_repeated_id_is_refused():
    with pytest.raises(ValueError, match="repeats"):
        subject.build({**header(), "concepts": [concept("A"), concept("A")]}, "WHO", "ICD-10-WHO")


def test_mappings_come_after_all_concepts(export):
    export["mappings"] = [{"type": "Mapping", "id": "m1", "map_type": "SAME-AS", "uuid": "x",
                           "from_concept_url": f"{BASE}/A00/", "to_concept_url": f"{BASE}/B09/"}]
    lines = lines_of(export)["lines"]
    assert lines[-1]["type"] == "Mapping" and lines[-1]["owner"] == "WHO" and "uuid" not in lines[-1]
    assert all(l["type"] == "Concept" for l in lines[:-1])


def write(path, export):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export.json", json.dumps(export))
    return path


def test_cli_writes_the_files_and_is_deterministic(export, tmp_path, capsys):
    source = write(tmp_path / "export.zip", export)
    for run in ("a", "b"):
        assert subject.main(["--export", str(source), "--out-dir", str(tmp_path / run), "--max-part-size", "380b"]) == 0
    first, second = tmp_path / "a", tmp_path / "b"
    names = sorted(p.name for p in first.iterdir())
    assert {"source.create.json", "post_import.patch.json", "replica_manifest.json", "replica_part_001.ndjson", "replica_part_001.zip"} <= set(names)
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    manifest = json.loads((first / "replica_manifest.json").read_text(encoding="utf-8"))
    assert manifest["input"]["file"] == "export.zip" and manifest["counts"]["concepts"] == 6
    assert manifest["upload"] == {**manifest["upload"], "mechanism": "manual", "api_upload": False}
    assert str(tmp_path) not in (first / "replica_manifest.json").read_text(encoding="utf-8")
    parts = sorted(first.glob("replica_part_*.ndjson"))
    zips = sorted(first.glob("replica_part_*.zip"))
    assert len(parts) > 1 and [z.stem for z in zips] == [p.stem for p in parts]
    assert all(z.stat().st_size <= 380 for z in zips)          # the cap is on the COMPRESSED upload zip
    assert manifest["upload"]["note"].count("ZIPs") == 1 and [p["zip"] for p in manifest["parts"]] == [z.name for z in zips]
    assert [json.loads(l)["id"] for p in parts for l in p.read_text(encoding="utf-8").splitlines()][0] in ("ICD-10", "ORPHAN")


def test_cli_rejects_something_that_is_not_an_export(tmp_path, capsys):
    bad = tmp_path / "x.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    assert subject.main(["--export", str(bad), "--out-dir", str(tmp_path / "o")]) == 2
    assert "not a Source version export" in capsys.readouterr().err


def test_the_tool_has_no_network_or_upload_surface():
    source = open(subject.__file__, encoding="utf-8").read()
    for marker in ("urllib.request", "urlopen", "requests", "socket", "OCL_API_TOKEN", "--upload"):
        assert marker not in source
