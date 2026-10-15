"""Untyped Foundation aliases in the ICD-11 build: flat codes, post-coordinated codes, one bundle.

Decision (owner): every alias is written as a name WITHOUT a ``name_type`` (the key is omitted, so OCL
stores null), never the string ``"None"``. They are lexical aliases of WHO Foundation entities, not a
claim of semantic equivalence: the flat entities are narrower/residual roll-ups of the code.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from ocl_pipeline_loader import load

st = load("who/icd-11", "simple_tabulation")
bulk = load("who/icd-11", "build_bulkimport")
flat = load("who/icd-11", "flat_synonyms")
fi = load("who/icd-11", "foundation_index")
pc = load("who/icd-11", "postcoordinated")
main = load("who/icd-11", "cli").main

BASE = "http://id.who.int/icd/release/11/2026-01/mms"
COMPOSITE = f"{BASE}/1 & {BASE}/2"


def alias(name, foundation_id="10", evidence="narrower"):
    return flat.FlatAlias(name=name, foundation_id=foundation_id, evidence=evidence)


def names_of(line):
    return [entry["name"] for entry in line["names"]]


# --- name entry shape ---------------------------------------------------------------------------


def test_alias_entries_have_no_name_type_key_and_are_not_preferred():
    entry = bulk.alias_name_entry("Enteritis due to cholera")
    assert entry == {"name": "Enteritis due to cholera", "locale": "en", "locale_preferred": False}
    assert "name_type" not in entry


# --- flat aliases in the base build -------------------------------------------------------------


def test_flat_aliases_follow_the_fully_specified_name_on_the_matching_concept(ordered_txt):
    result = bulk.build(st.read(ordered_txt), flat_aliases={"1A00": [alias("Enteritis due to cholera"), alias("Cholera, non-O1")]})
    cholera = next(line for line in result.lines if line["id"] == "1A00")
    assert names_of(cholera) == ["Cholera", "Enteritis due to cholera", "Cholera, non-O1"]
    assert cholera["names"][0]["name_type"] == "Fully Specified"
    assert all("name_type" not in entry for entry in cholera["names"][1:])
    assert result.alias_stats["names_added"] == 2
    assert result.alias_stats["concepts_with_aliases"] == 1


def test_an_alias_equal_to_the_fully_specified_name_is_dropped_and_counted(ordered_txt):
    result = bulk.build(st.read(ordered_txt), flat_aliases={"1A00": [alias("cholera"), alias("Other")]})
    cholera = next(line for line in result.lines if line["id"] == "1A00")
    assert names_of(cholera) == ["Cholera", "Other"]
    assert result.alias_stats["equal_to_fsn"] == 1


def test_an_unknown_code_is_reported_never_dropped_silently(ordered_txt):
    result = bulk.build(st.read(ordered_txt), flat_aliases={"ZZ99": [alias("Ghost")]})
    assert result.alias_stats["unknown_codes"] == ["ZZ99"]
    assert result.alias_stats["names_added"] == 0
    assert all("Ghost" not in names_of(line) for line in result.lines)


def test_build_without_aliases_is_unchanged(ordered_txt):
    plain = bulk.build(st.read(ordered_txt))
    assert all(len(line["names"]) == 1 for line in plain.lines)
    assert plain.alias_stats["names_added"] == 0


# --- post-coordinated aliases ---------------------------------------------------------------------


def make_row(**kwargs):
    base = dict(
        code="1A00&XN62R", title="Cholera [Vibrio cholerae O1, biovar eltor]", entity_id=COMPOSITE,
        stem_code="1A00", axes=("infectiousAgent",), extension_codes=("XN62R",), extension_labels=("Vibrio",),
        describe_status="ok", describe_error="", browse_url="", source_row=2,
    )
    base.update(kwargs)
    return pc.PostcoordRow(**base)


def test_postcoord_concept_line_appends_untyped_alias_names():
    line = bulk.postcoord_concept_line(make_row(), alias_names=("cholera O1", "Cholera classical"))
    assert names_of(line) == ["Cholera [Vibrio cholerae O1, biovar eltor]", "cholera O1", "Cholera classical"]
    assert "name_type" not in line["names"][1]


def test_postcoord_aliases_merge_index_entities_and_csv_synonyms_without_repeats():
    entity = fi.IndexEntity("555", "Cholera due to O1", ("cholera O1",))
    row = make_row(synonyms=("Cholera O1", "classical cholera"))
    result = bulk.build_postcoordinated(
        pc.PostcoordIndex(release="2026-01", rows=[row]), known_stem_ids={"1A00"},
        index_entities={COMPOSITE: [entity]},
    )
    assert names_of(result.concept_lines[0]) == [
        "Cholera [Vibrio cholerae O1, biovar eltor]", "Cholera due to O1", "cholera O1", "classical cholera",
    ]
    assert result.alias_stats["names_added"] == 3
    assert result.alias_stats["rows_with_aliases"] == 1


def test_a_row_whose_composite_is_absent_from_the_index_is_reported():
    row = make_row()
    result = bulk.build_postcoordinated(
        pc.PostcoordIndex(release="2026-01", rows=[row]), known_stem_ids={"1A00"}, index_entities={},
    )
    assert result.alias_stats["rows_without_index_entities"] == ["1A00&XN62R"]
    assert len(result.concept_lines) == 1  # still built: the index only adds aliases


def test_an_index_title_equal_to_the_row_title_is_not_repeated():
    entity = fi.IndexEntity("555", "cholera [vibrio cholerae o1, biovar eltor]", ())
    result = bulk.build_postcoordinated(
        pc.PostcoordIndex(release="2026-01", rows=[make_row()]), known_stem_ids={"1A00"},
        index_entities={COMPOSITE: [entity]},
    )
    assert len(result.concept_lines[0]["names"]) == 1
    assert result.alias_stats["equal_to_fsn"] == 1


def test_the_reader_keeps_csv_synonyms_as_a_tuple(tmp_path):
    fields = [
        "entity_id", "browser_link", "code", "title", "title_source", "title_composed", "foundation_entity_id",
        "foundation_browser_link", "describe_status", "describe_error", "stem_code", "stem_label",
        "stem_linearization_uri", "stem_foundation_uri", "axes", "extension_codes", "extension_labels",
        "definition", "synonyms", "parent_foundation_ids",
    ]
    path = tmp_path / "full.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({**{name: "" for name in fields}, "entity_id": COMPOSITE, "code": "1A00&XN62R",
                         "title": "Cholera [O1]", "describe_status": "ok", "synonyms": "a | b"})
    index = pc.read(path, release="2026-01")
    assert index.rows[0].synonyms == ("a", "b")


# --- CLI: one bundle -------------------------------------------------------------------------------

from test_icd11_foundation_index import FLAT_FIELDS, build_index, flat_row, index_record, shared_info, field, write_flat  # noqa: E402
from test_postcoordinated import FULL_CSV_FIELDS  # noqa: E402


def make_inputs(tmp_path: Path):
    """A tabulation-compatible full CSV (1A00&XN62R ok), a flat CSV for 1A00, and a matching index."""
    full = tmp_path / "full.csv"
    row = {name: "" for name in FULL_CSV_FIELDS}
    row.update({
        "entity_id": COMPOSITE, "code": "1A00&XN62R", "title": "Cholera [Vibrio cholerae O1, biovar eltor]",
        "title_source": "foundation_entity", "describe_status": "ok", "stem_code": "1A00",
        "axes": "infectiousAgent", "extension_codes": "XN62R", "extension_labels": "Vibrio",
    })
    with full.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FULL_CSV_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    flat_csv = write_flat(tmp_path / "flat.csv", [
        flat_row("1A00", "Enteritis due to cholera", "10"),
        flat_row("1A00", "Cholera, non-O1", "11", evidence="residual_rollup"),
        flat_row("1A00", "Cholera", "12"),                      # equals the FSN: dropped
        flat_row("ZZ99", "Ghost", "13"),                         # not in the base
    ])
    index_file = tmp_path / "ix.pbf"
    index_file.write_bytes(build_index(
        [("Cholera due to O1", 555), ("cholera O1", 0)],
        [index_record(0, 0, COMPOSITE), index_record(1, 0, COMPOSITE)],
    ))
    return full, flat_csv, index_file


def combined_args(tmp_path, ordered_txt, full, flat_csv, index_file, *extra):
    return [
        "build", "--input", str(ordered_txt), "--output-dir", str(tmp_path / "output"),
        "--flat-synonyms", str(flat_csv), "--postcoordinated-csv", str(full), "--index-file", str(index_file), *extra,
    ]


def read_bundle(tmp_path):
    return [json.loads(line) for line in (tmp_path / "output" / "bulkimport_bundle.ndjson").read_text().splitlines()]


def test_cli_builds_one_bundle_with_base_aliases_postcoordinated_concepts_and_mappings(tmp_path, ordered_txt):
    full, flat_csv, index_file = make_inputs(tmp_path)
    assert main(combined_args(tmp_path, ordered_txt, full, flat_csv, index_file)) == 0
    lines = read_bundle(tmp_path)
    by_id = {line["id"]: line for line in lines if line["type"] == "Concept"}
    assert names_of(by_id["1A00"]) == ["Cholera", "Enteritis due to cholera", "Cholera, non-O1"]
    assert names_of(by_id["1A00&XN62R"])[1:] == ["Cholera due to O1", "cholera O1"]
    mappings = [line for line in lines if line["type"] == "Mapping"]
    assert [m["map_type"] for m in mappings] == ["NARROWER-THAN"]
    # base first, then post-coordinated concepts, then mappings: OCL imports in order
    kinds = [line["type"] for line in lines]
    assert kinds == sorted(kinds, key=lambda kind: kind == "Mapping")
    assert lines.index(by_id["1A00"]) < lines.index(by_id["1A00&XN62R"])
    assert not any("name_type" in n for line in lines if line["type"] == "Concept"
                   for n in line["names"][1:])


def test_cli_audit_records_inputs_name_policy_and_unmatched_items(tmp_path, ordered_txt):
    full, flat_csv, index_file = make_inputs(tmp_path)
    assert main(combined_args(tmp_path, ordered_txt, full, flat_csv, index_file)) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text())
    assert audit["mode"] == "full-source-load"
    assert audit["upload_ready"]["local"]["status"] is False
    roles = {entry["role"] for entry in audit["inputs"]}
    assert {"simple-tabulation", "flat-foundation-synonyms-csv", "postcoordinated-index-full-csv", "icd-api-search-index"} <= roles
    aliases = audit["aliases"]
    assert aliases["name_type"] == "omitted (null)"
    assert aliases["flat"]["names_added"] == 2
    assert aliases["flat"]["equal_to_fsn"] == 1
    assert aliases["flat"]["unknown_codes"] == ["ZZ99"]
    assert aliases["flat"]["evidence"] == {"narrower": 3, "residual_rollup": 1}
    assert aliases["postcoordinated"]["names_added"] == 2
    assert audit["build"]["postcoordinated_concepts"] == 1 and audit["build"]["postcoordinated_mappings"] == 1
    assert "post-coordinated codes" not in audit["projection"]["omitted"]
    text = json.dumps(audit)
    assert str(tmp_path) not in text and "/Users/" not in text


def test_cli_combined_rebuild_is_byte_identical(tmp_path, ordered_txt):
    full, flat_csv, index_file = make_inputs(tmp_path)
    outputs = []
    for run in ("one", "two"):
        run_dir = tmp_path / run
        run_dir.mkdir()
        args = combined_args(run_dir, ordered_txt, full, flat_csv, index_file)
        assert main(args) == 0
        outputs.append(run_dir / "output")
    for name in ("bulkimport_bundle.ndjson", "bulkimport_audit.json", "bulkimport_icd11-who.bundle.zip"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name


def test_cli_refuses_a_postcoordinated_csv_without_the_index_file(tmp_path, ordered_txt, capsys):
    full, flat_csv, _ = make_inputs(tmp_path)
    code = main([
        "build", "--input", str(ordered_txt), "--output-dir", str(tmp_path / "output"),
        "--postcoordinated-csv", str(full),
    ])
    assert code == 1
    assert "--index-file" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()


def test_cli_refuses_an_index_file_without_a_postcoordinated_csv(tmp_path, ordered_txt, capsys):
    _, _, index_file = make_inputs(tmp_path)
    code = main([
        "build", "--input", str(ordered_txt), "--output-dir", str(tmp_path / "output"), "--index-file", str(index_file),
    ])
    assert code == 1
    assert "--postcoordinated-csv" in capsys.readouterr().err


def test_flat_synonyms_alone_leave_the_bundle_as_a_base_load(tmp_path, ordered_txt):
    _, flat_csv, _ = make_inputs(tmp_path)
    code = main([
        "build", "--input", str(ordered_txt), "--output-dir", str(tmp_path / "output"),
        "--flat-synonyms", str(flat_csv),
    ])
    assert code == 0
    lines = read_bundle(tmp_path)
    assert all(line["type"] == "Concept" for line in lines)
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text())
    assert "postcoordinated" not in audit["aliases"]
    assert "post-coordinated codes" in audit["projection"]["omitted"]


def test_default_build_has_no_aliases_block(tmp_path, ordered_txt):
    assert main(["build", "--input", str(ordered_txt), "--output-dir", str(tmp_path / "output")]) == 0
    audit = json.loads((tmp_path / "output" / "bulkimport_audit.json").read_text())
    assert "aliases" not in audit


def test_additive_postcoordinated_command_also_takes_the_index_file(tmp_path, tabulation_zip):
    full, _, index_file = make_inputs(tmp_path)
    output_dir = tmp_path / "additive"
    assert main([
        "build-postcoordinated", "--input", str(full), "--simple-tabulation", str(tabulation_zip),
        "--index-file", str(index_file), "--output-dir", str(output_dir),
    ]) == 0
    lines = [json.loads(line) for line in (output_dir / "bulkimport_bundle.ndjson").read_text().splitlines()]
    concept = next(line for line in lines if line["type"] == "Concept")
    assert names_of(concept)[1:] == ["Cholera due to O1", "cholera O1"]
    audit = json.loads((output_dir / "bulkimport_audit.json").read_text())
    assert audit["mode"] == "incremental-add"
    assert audit["aliases"]["postcoordinated"]["names_added"] == 2
    assert {entry["role"] for entry in audit["inputs"]} >= {"icd-api-search-index"}


def test_additive_postcoordinated_command_without_an_index_has_no_aliases_block(tmp_path, tabulation_zip):
    full, _, _ = make_inputs(tmp_path)
    output_dir = tmp_path / "additive"
    assert main([
        "build-postcoordinated", "--input", str(full), "--simple-tabulation", str(tabulation_zip),
        "--output-dir", str(output_dir),
    ]) == 0
    audit = json.loads((output_dir / "bulkimport_audit.json").read_text())
    assert "aliases" not in audit


# --- Foundation URL of post-coordinated concepts ------------------------------------------------------


def foundation_url_of(row, entities):
    result = bulk.build_postcoordinated(
        pc.PostcoordIndex(release="2026-01", rows=[row]), known_stem_ids={"1A00"}, index_entities=entities,
    )
    return result.concept_lines[0]["extras"].get("Foundation URL"), result.foundation_stats


def test_own_foundation_entity_of_the_row_wins():
    url, stats = foundation_url_of(make_row(foundation_entity_id="555"), {COMPOSITE: [fi.IndexEntity("555", "T", ())]})
    assert url == "https://icd.who.int/browse/2026-01/foundation/en#555"
    assert stats["from_own_entity"] == 1


def test_a_single_index_entity_is_used_when_the_row_has_no_own_entity():
    url, stats = foundation_url_of(make_row(), {COMPOSITE: [fi.IndexEntity("777", "T", ())]})
    assert url.endswith("#777") and stats["from_single_index_entity"] == 1


def test_several_index_entities_without_an_own_one_leave_the_url_out_and_are_counted():
    entities = {COMPOSITE: [fi.IndexEntity("1", "A", ()), fi.IndexEntity("2", "B", ())]}
    url, stats = foundation_url_of(make_row(), entities)
    assert url is None and stats["ambiguous_not_set"] == 1


def test_an_own_entity_missing_from_the_index_is_still_used_and_reported():
    url, stats = foundation_url_of(make_row(foundation_entity_id="555"), {COMPOSITE: [fi.IndexEntity("999", "T", ())]})
    assert url.endswith("#555") and stats["own_not_in_index"] == 1


# --- Foundation URL of base concepts --------------------------------------------------------------------


def test_base_concepts_with_a_foundation_uri_get_the_pinned_foundation_url(ordered_txt):
    result = bulk.build(st.read(ordered_txt))
    cholera = next(line for line in result.lines if line["id"] == "1A00")
    assert cholera["extras"]["Foundation URL"] == "https://icd.who.int/browse/2026-01/foundation/en#300"
    assert "Foundation URL" not in result.lines[0].get("extras", {})  # the synthetic root has no WHO entity
