"""WHOCC ATC_ddd.xml reader and the ``DDD`` extra projection."""

from __future__ import annotations

import json
import zipfile

import pytest

from ocl_pipeline_loader import load

ddd_xml = load("who/atc", "ddd_xml")
who_update = load("who/atc", "who_update")

HEADER = (
    "<xml xmlns:s='uuid:BDC6E3F0-6DA3-11d1-A2A3-00AA00C14882' xmlns:dt='uuid:C2F41010-65B3-11d1-A29F-00AA00C14882' "
    "xmlns:rs='urn:schemas-microsoft-com:rowset' xmlns:z='#RowsetSchema'>\r\n<s:Schema id='RowsetSchema'/>\r\n<rs:data>\r\n"
)


def write_xml(tmp_path, rows: str, name="ddd.xml"):
    path = tmp_path / name
    path.write_text(f"{HEADER}{rows}\r\n</rs:data>\r\n</xml>", encoding="utf-8")
    return path


def project(tmp_path, rows: str, codes: set[str]):
    return ddd_xml.project(ddd_xml.read_rows(write_xml(tmp_path, rows)), codes)


def test_one_entry_per_row_in_file_order_with_route_expanded(tmp_path):
    result = project(
        tmp_path,
        "\t<z:row ATCCode='A06AB02' DDD='10' UnitType='mg' AdmCode='O'/>\r\n"
        "\t<z:row ATCCode='A06AB02' DDD='10' UnitType='mg' AdmCode='R'/>",
        {"A06AB02"},
    )
    assert result.extras == {"A06AB02": "10 mg (oral)" + ddd_xml.LINE_SEPARATOR + "10 mg (rectal)"}


def test_comment_goes_last_and_same_route_rows_stay_distinct(tmp_path):
    result = project(
        tmp_path,
        "<z:row ATCCode='A10BB01' DDD='7' UnitType='mg' AdmCode='O' DDDComment='microcryst.substance'/>"
        "<z:row ATCCode='A10BB01' DDD='10' UnitType='mg' AdmCode='O'/>",
        {"A10BB01"},
    )
    assert result.extras["A10BB01"].split(ddd_xml.LINE_SEPARATOR) == ["7 mg (oral) microcryst.substance", "10 mg (oral)"]


def test_partial_rows_are_kept_as_published_and_counted(tmp_path):
    result = project(
        tmp_path,
        "<z:row ATCCode='S01EB01' DDD='0.4' UnitType='ml'/>"
        "<z:row ATCCode='S01EB01' DDD='0.285' AdmCode='lamella'/>",
        {"S01EB01"},
    )
    assert result.extras["S01EB01"].split(ddd_xml.LINE_SEPARATOR) == ["0.4 ml", "0.285 (lamella)"]
    assert result.stats["written_rows_without_route"] == 1
    assert result.stats["written_rows_without_unit"] == 1
    assert result.stats["routes_outside_whocc_legend"] == {"lamella": 1}


def test_rows_without_a_ddd_value_write_nothing(tmp_path):
    result = project(
        tmp_path,
        "<z:row ATCCode='S01ED01' DDD=''/>"
        "<z:row ATCCode='S01EE02' DDD='' DDDComment=''/>"
        "<z:row ATCCode='A02BA01' DDD='0.8' UnitType='g' AdmCode='O'/>",
        {"S01ED01", "S01EE02", "A02BA01"},
    )
    assert set(result.extras) == {"A02BA01"}
    assert result.stats["rows_skipped_empty_ddd"] == 2
    assert result.stats["codes_skipped_empty_ddd"] == ["S01ED01", "S01EE02"]


def test_whitespace_is_trimmed_and_empty_comment_attribute_is_ignored(tmp_path):
    result = project(
        tmp_path,
        "<z:row ATCCode='V03AG05 ' DDD='1' UnitType='g' AdmCode='s.c. implant  ' DDDComment=''/>",
        {"V03AG05"},
    )
    assert result.extras == {"V03AG05": "1 g (s.c. implant)"}


def test_unknown_route_values_stay_literal(tmp_path):
    result = project(tmp_path, "<z:row ATCCode='R03AC02' DDD='1' UnitType='mg' AdmCode='Inhal.solution'/>", {"R03AC02"})
    assert result.extras == {"R03AC02": "1 mg (Inhal.solution)"}


def test_code_absent_from_the_snapshot_aborts(tmp_path):
    with pytest.raises(ValueError, match="absent from the WHOCC snapshot"):
        project(tmp_path, "<z:row ATCCode='Z99ZZ99' DDD='1' UnitType='g'/>", {"A"})


def test_unexpected_attribute_or_empty_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unexpected attributes"):
        ddd_xml.read_rows(write_xml(tmp_path, "<z:row ATCCode='A' DDD='1' Surprise='x'/>"))
    with pytest.raises(ValueError, match="no <z:row>"):
        ddd_xml.read_rows(write_xml(tmp_path, ""))


def snapshot():
    return {"records": [
        {"code": "A", "title": "Chapter", "level": 1, "parent": None},
        {"code": "A01", "title": "Group", "level": 2, "parent": "A"},
    ]}


def concept(concept_id, concept_class="Code"):
    return {
        "type": "Concept", "id": concept_id, "owner": "WHO", "owner_type": "Organization", "source": "WHOATC",
        "retired": False, "concept_class": concept_class, "datatype": "None",
        "names": [{"name": concept_id, "locale": "en", "locale_preferred": True}], "descriptions": [], "extras": {},
    }


def test_who_update_writes_ddd_only_where_given():
    export = {"concepts": [concept("Root", "Root"), concept("A")], "mappings": []}
    result = who_update.build(snapshot(), export, {"A01": "5 mg (oral)"})
    extras = {line["id"]: line["extras"] for line in result.lines if "extras" in line}
    assert extras["A"] == {"ATC Level": 1, "Is_Drug_Class": "Y"}
    assert extras["A01"] == {"ATC Level": 2, "Is_Drug_Class": "Y", "DDD": "5 mg (oral)"}


def test_who_update_rejects_ddd_for_a_code_outside_the_snapshot():
    export = {"concepts": [concept("Root", "Root")], "mappings": []}
    with pytest.raises(ValueError, match="absent from the WHOCC snapshot"):
        who_update.build(snapshot(), export, {"B99": "1 g"})


def test_cli_requires_the_ddd_file_and_records_it_in_the_audit(tmp_path):
    cli = load("who/atc", "cli")
    snapshot_path = tmp_path / "who.json"
    export_path = tmp_path / "before.json"
    snapshot_path.write_text(json.dumps(snapshot()), encoding="utf-8")
    export_path.write_text(json.dumps({
        "owner": "WHO", "short_code": "WHOATC", "source": {},
        "concepts": [concept("Root", "Root")], "mappings": [],
    }), encoding="utf-8")
    ddd_path = write_xml(
        tmp_path,
        "<z:row ATCCode='A01' DDD='5' UnitType='mg' AdmCode='O'/><z:row ATCCode='A01' DDD='' />",
    )
    out = tmp_path / "build"
    with pytest.raises(SystemExit):  # --ddd-xml is required
        cli.main(["build-who-update", "--snapshot", str(snapshot_path), "--export", str(export_path), "--output-dir", str(out)])
    assert cli.main([
        "build-who-update", "--snapshot", str(snapshot_path), "--export", str(export_path),
        "--ddd-xml", str(ddd_path), "--output-dir", str(out),
    ]) == 0
    audit = json.loads((out / "bulkimport_audit.json").read_text(encoding="utf-8"))
    entry = next(item for item in audit["inputs"] if item["role"] == "who-atc-ddd-release-xml")
    assert len(entry["sha256"]) == 64 and entry["codes_with_ddd"] == 1 and entry["rows_skipped_empty_ddd"] == 1
    with zipfile.ZipFile(out / "bulkimport_whoatc.local.bundle.zip") as archive:
        lines = [json.loads(row) for row in archive.read("bulkimport_bundle.ndjson").decode("utf-8").splitlines()]
    assert next(line for line in lines if line["id"] == "A01")["extras"]["DDD"] == "5 mg (oral)"
