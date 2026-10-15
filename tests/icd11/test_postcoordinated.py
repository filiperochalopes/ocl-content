"""Tests for the post-coordinated add-on layer: reader, concept/mapping builder, and the CLI."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from ocl_pipeline_loader import load

pc = load("who/icd-11", "postcoordinated")
bulk = load("who/icd-11", "build_bulkimport")
review = load("who/icd-11", "review")
main = load("who/icd-11", "cli").main

FULL_CSV_FIELDS = [
    "entity_id", "browser_link", "code", "title", "title_source", "title_composed",
    "foundation_entity_id", "foundation_browser_link", "describe_status", "describe_error",
    "stem_code", "stem_label", "stem_linearization_uri", "stem_foundation_uri",
    "axes", "extension_codes", "extension_labels", "definition", "synonyms", "parent_foundation_ids",
]

ROWS = [
    {
        "entity_id": "http://id.who.int/icd/release/11/2026-01/mms/1 & http://id.who.int/icd/release/11/2026-01/mms/2",
        "browser_link": "http://localhost:8887/browse/2026-01/mms/en#1%20%26%202",
        "code": "1A00&XN62R", "title": "Cholera [Vibrio cholerae O1, biovar eltor]",
        "title_source": "foundation_entity", "title_composed": "Cholera [Vibrio cholerae O1, biovar eltor]",
        "foundation_entity_id": "555", "foundation_browser_link": "https://icd.who.int/browse/2026-01/foundation/en#555",
        "describe_status": "ok", "describe_error": "", "stem_code": "1A00", "stem_label": "Cholera",
        "stem_linearization_uri": "", "stem_foundation_uri": "",
        "axes": "infectiousAgent", "extension_codes": "XN62R", "extension_labels": "Vibrio cholerae O1, biovar eltor",
        "definition": "An infection.", "synonyms": "cholera O1", "parent_foundation_ids": "1",
    },
    {
        # A rejected row: stem_code/stem_label are empty (as the real export leaves them when /describe fails),
        # and the composite code uses "/" — the reader must still derive the stem from the code itself.
        "entity_id": "http://id.who.int/icd/release/11/2026-01/mms/3 / http://id.who.int/icd/release/11/2026-01/mms/4",
        "browser_link": "http://localhost:8887/browse/2026-01/mms/en#3%20%2F%204",
        "code": "5B81.Y/1A00", "title": "Other specified obesity / Cholera",
        "title_source": "composed_from_components", "title_composed": "Other specified obesity / Cholera",
        "foundation_entity_id": "", "foundation_browser_link": "",
        "describe_status": "rejected_by_api", "describe_error": "the entity 1A00 does not exist in any valueset",
        "stem_code": "", "stem_label": "", "stem_linearization_uri": "", "stem_foundation_uri": "",
        "axes": "", "extension_codes": "", "extension_labels": "",
        "definition": "", "synonyms": "", "parent_foundation_ids": "",
    },
    {
        # A second "ok" row whose stem is NOT in the (tiny) base tabulation fixture used below.
        "entity_id": "http://id.who.int/icd/release/11/2026-01/mms/9 & http://id.who.int/icd/release/11/2026-01/mms/8",
        "browser_link": "", "code": "ZZ99&XN8KD", "title": "Unknown stem example",
        "title_source": "composed_from_components", "title_composed": "Unknown stem example",
        "foundation_entity_id": "", "foundation_browser_link": "",
        "describe_status": "ok", "describe_error": "", "stem_code": "ZZ99", "stem_label": "",
        "stem_linearization_uri": "", "stem_foundation_uri": "",
        "axes": "infectiousAgent", "extension_codes": "XN8KD", "extension_labels": "Vibrio cholerae O139",
        "definition": "", "synonyms": "", "parent_foundation_ids": "",
    },
]


@pytest.fixture
def full_csv(tmp_path) -> Path:
    path = tmp_path / "postcoord_index_items_full.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FULL_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    return path


# --- reader ------------------------------------------------------------------------------------


def test_default_read_keeps_only_ok_rows(full_csv):
    index = pc.read(full_csv, release="2026-01")
    assert [row.code for row in index.rows] == ["1A00&XN62R", "ZZ99&XN8KD"]
    assert index.total_read == 3
    assert index.skipped == [{"reason": "describe_status=rejected_by_api", "source_row": 3}]


def test_include_rejected_keeps_every_row_and_derives_stem_from_the_code(full_csv):
    index = pc.read(full_csv, release="2026-01", include_rejected=True)
    by_code = {row.code: row for row in index.rows}
    assert set(by_code) == {"1A00&XN62R", "5B81.Y/1A00", "ZZ99&XN8KD"}
    rejected = by_code["5B81.Y/1A00"]
    assert rejected.stem_code == "5B81.Y"  # derived from the code, NOT the empty stem_code column
    assert rejected.describe_status == "rejected_by_api"
    assert rejected.describe_error == "the entity 1A00 does not exist in any valueset"


def test_first_stem_code_splits_on_the_first_separator_only():
    assert pc.first_stem_code("1A00&XN62R") == "1A00"
    assert pc.first_stem_code("5B81.Y/1A00") == "5B81.Y"
    assert pc.first_stem_code("1A0Y/MG51.00&XN6BM") == "1A0Y"


def test_public_browse_url_reconstructs_the_icd_who_int_anchor():
    entity_id = "http://id.who.int/icd/release/11/2026-01/mms/1 & http://id.who.int/icd/release/11/2026-01/mms/2"
    assert pc.public_browse_url(entity_id, "2026-01") == "https://icd.who.int/browse/2026-01/mms/en#1%20%26%202"


def test_missing_columns_raise(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("code,title\n1A00,Cholera\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        pc.read(path, release="2026-01")


# --- concept / mapping line builder -------------------------------------------------------------


def _index(rows, release="2026-01"):
    return pc.PostcoordIndex(release=release, rows=list(rows))


def _row(**kwargs):
    base = dict(
        code="1A00&XN62R", title="Cholera [Vibrio cholerae O1, biovar eltor]",
        entity_id="http://id.who.int/icd/release/11/2026-01/mms/1 & http://id.who.int/icd/release/11/2026-01/mms/2",
        stem_code="1A00", axes=("infectiousAgent",), extension_codes=("XN62R",),
        extension_labels=("Vibrio cholerae O1, biovar eltor",), describe_status="ok", describe_error="",
        browse_url="https://icd.who.int/browse/2026-01/mms/en#1%20%26%202", source_row=2,
    )
    base.update(kwargs)
    return pc.PostcoordRow(**base)


def test_concept_line_carries_the_raw_code_as_id_with_no_parent_url():
    line = bulk.postcoord_concept_line(_row())
    assert line["id"] == "1A00&XN62R"
    assert line["concept_class"] == "Diagnosis"
    assert "parent_concept_urls" not in line
    assert line["extras"]["isPostcoordinated"] == "True"


def test_the_only_post_coordination_extra_is_isPostcoordinated():
    extras = bulk.postcoord_concept_line(_row(), foundation_id="555", release="2026-01")["extras"]
    assert set(extras) == {"isLeaf", "BrowserLink", "isPostcoordinated", "Foundation URI", "Foundation URL"}
    for dropped in ("is_postcoordinated", "Entity ID", "StemCode", "Axes", "DescribeStatus"):
        assert dropped not in extras


def test_foundation_uri_is_the_standard_who_entity_uri_next_to_the_url():
    extras = bulk.postcoord_concept_line(_row(), foundation_id="704377697", release="2026-01")["extras"]
    assert extras["Foundation URI"] == "http://id.who.int/icd/entity/704377697"


def test_foundation_url_is_the_pinned_official_foundation_browser_link():
    extras = bulk.postcoord_concept_line(_row(), foundation_id="704377697", release="2026-01")["extras"]
    assert extras["Foundation URL"] == "https://icd.who.int/browse/2026-01/foundation/en#704377697"


def test_without_a_foundation_id_there_is_neither_foundation_uri_nor_url():
    extras = bulk.postcoord_concept_line(_row())["extras"]
    assert "Foundation URL" not in extras and "Foundation URI" not in extras


def test_a_post_coordinated_code_must_contain_an_ampersand_or_a_slash():
    with pytest.raises(ValueError, match="not a composite"):
        bulk.postcoord_concept_line(_row(code="1A00"))


def test_postcoordinated_concept_is_a_leaf_with_a_latest_browser_link_like_any_other_concept():
    extras = bulk.postcoord_concept_line(_row())["extras"]
    assert extras["isLeaf"] == "True"
    assert extras["BrowserLink"] == "https://icd.who.int/browse/latestrelease/mms/en#1%20%26%202"


def test_postcoordinated_concept_carries_no_extension_error_or_pinned_link_extras():
    line = bulk.postcoord_concept_line(_row(
        code="5B81.Y/1A00", stem_code="5B81.Y", describe_status="rejected_by_api",
        describe_error="the entity 1A00 does not exist in any valueset",
    ))
    for dropped in ("ExtensionCodes", "ExtensionLabels", "DescribeError", "BrowseURL"):
        assert dropped not in line["extras"]


def test_mapping_percent_encodes_a_slash_in_from_concept_url():
    row = _row(code="5B81.Y/1A00", stem_code="1A00")
    line = bulk.postcoord_mapping_line(row)
    assert line["map_type"] == "NARROWER-THAN"
    assert line["from_concept_url"] == "/orgs/WHO/sources/ICD-11-WHO/concepts/5B81.Y%2F1A00/"
    assert line["to_concept_url"] == "/orgs/WHO/sources/ICD-11-WHO/concepts/1A00/"


def test_build_postcoordinated_skips_unknown_stems_and_reports_them():
    rows = [_row(), _row(code="ZZ99&X", stem_code="ZZ99")]
    result = bulk.build_postcoordinated(_index(rows), known_stem_ids={"1A00"})
    assert [line["id"] for line in result.concept_lines] == ["1A00&XN62R"]
    assert len(result.mapping_lines) == 1
    assert result.unknown_stems == ["ZZ99&X"]


# --- CLI end to end ------------------------------------------------------------------------------


def test_cli_build_postcoordinated_end_to_end(tmp_path, full_csv, tabulation_zip):
    output_dir = tmp_path / "output"
    exit_code = main([
        "build-postcoordinated",
        "--input", str(full_csv),
        "--simple-tabulation", str(tabulation_zip),
        "--output-dir", str(output_dir),
        "--max-part-size", "64kb",
    ])
    assert exit_code == 0
    audit = json.loads((output_dir / "bulkimport_audit.json").read_text())
    assert audit["mode"] == "incremental-add"
    assert audit["upload_ready"]["local"]["status"] is False
    assert audit["build"]["concept_lines"] == 1  # only the "ok" row whose stem (1A00) exists in the fixture
    assert audit["build"]["mapping_lines"] == 1
    assert audit["build"]["unknown_stems"] == ["ZZ99&XN8KD"]
    assert (output_dir / "bulkimport_icd11-who-postcoord.bundle.zip").is_file()


def test_cli_rejects_a_postcoordinated_id_that_collides_with_the_base_source(tmp_path, tabulation_zip):
    # "1A00" is already a base concept id; a post-coordinated code can never equal a bare stem code
    # (it always carries & or /), but the guard itself is exercised directly here.
    colliding_csv = tmp_path / "colliding.csv"
    with colliding_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FULL_CSV_FIELDS)
        writer.writeheader()
        row = dict(ROWS[0])
        row["code"] = "1A00"  # pathological: would collide with the base concept of the same id
        row["stem_code"] = "1A00"
        writer.writerow(row)
    exit_code = main([
        "build-postcoordinated", "--input", str(colliding_csv), "--simple-tabulation", str(tabulation_zip),
        "--output-dir", str(tmp_path / "output"),
    ])
    assert exit_code == 1


def test_cli_review_writes_a_filterable_html_with_one_row_per_code_by_default(tmp_path, full_csv, tabulation_zip):
    output = tmp_path / "review.html"
    exit_code = main([
        "review", "--input", str(full_csv), "--simple-tabulation", str(tabulation_zip), "--output", str(output),
    ])
    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert text.count("<tr") - 1 == 3  # header row + all 3 fixture rows
    assert "5B81.Y/1A00" in text and "the entity 1A00 does not exist in any valueset" in text
    assert 'class="own">has Foundation code' in text  # the row with its own foundation entity
    assert "composed (no Foundation code)" in text  # the two rows without one
    assert "Foundation code: 1" in text  # exactly one of the three fixture rows has foundation_entity_id set


def test_cli_review_rows_rejected_filters_to_only_rejected(tmp_path, full_csv, tabulation_zip):
    output = tmp_path / "rejected.html"
    exit_code = main([
        "review", "--input", str(full_csv), "--simple-tabulation", str(tabulation_zip),
        "--output", str(output), "--rows", "rejected",
    ])
    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert text.count("<tr") - 1 == 1  # header + the one rejected fixture row (count both <tr> and <tr class=...)
    assert "5B81.Y/1A00" in text.split("<tbody>")[1]
    assert "1A00&XN62R" not in text.split("<tbody>")[1]


def test_review_rows_carry_filter_data_attributes():
    own_entity_row = _row(foundation_entity_id="555", foundation_browser_link="https://icd.who.int/browse/2026-01/foundation/en#555")
    multi_stem_row = _row(code="5B81.Y/1A00", stem_code="5B81.Y", extension_codes=())
    html_doc = review.render_review_html(
        [own_entity_row, multi_stem_row], release="2026-01",
        total_indexed=2, total_ok=2, total_rejected=0, total_own_entity=1,
    )
    assert 'data-foundation="1"' in html_doc and 'data-foundation="0"' in html_doc
    assert 'data-multistem="1"' in html_doc and 'data-multistem="0"' in html_doc
    assert 'data-ext="1"' in html_doc and 'data-ext="0"' in html_doc
    # own-entity row: a clickable Foundation code link showing its id; the other row gets the dash
    assert '<a href="https://icd.who.int/browse/2026-01/foundation/en#555" target="_blank">555</a>' in html_doc
    assert '<span class="dash">—</span>' in html_doc
    assert 'has Foundation code' in html_doc and 'composed (no Foundation code)' in html_doc
    # both rows still get an MMS link (works even without a Foundation code of its own)
    assert html_doc.count('target="_blank">pub</a>') == 2
    # select-based filter controls are present, not just the free-text box
    for select_id in ("f-status", "f-foundation", "f-multistem", "f-ext"):
        assert f'id="{select_id}"' in html_doc
    assert 'id="count"' in html_doc  # the live "Showing X of Y" counter
    assert "AND, not OR" in html_doc  # the filters narrow incrementally, documented in the script comment


def test_extension_presence_is_derived_from_the_code_not_the_hydrated_columns():
    # Regression for the exact pair reported: own-Foundation-entity codes that /describe stops
    # decomposing (empty extension_codes despite a real "&"), and second-stem codes where /describe
    # reports the second stem itself as an axis value (non-empty extension_codes despite no "&").
    has_amp_but_empty_hydration = _row(code="2D10.Y&XH3Z50", stem_code="2D10.Y", extension_codes=(), axes=())
    no_amp_but_hydrated_as_extension = _row(code="1A02/1G40", stem_code="1A02", extension_codes=("1G40",), axes=("hasManifestation",))

    assert has_amp_but_empty_hydration.has_extension_code is True
    assert has_amp_but_empty_hydration.extension_count == 1
    assert no_amp_but_hydrated_as_extension.has_extension_code is False
    assert no_amp_but_hydrated_as_extension.extension_count == 0

    html_doc = review.render_review_html(
        [has_amp_but_empty_hydration, no_amp_but_hydrated_as_extension], release="2026-01",
        total_indexed=2, total_ok=2, total_rejected=0, total_own_entity=0,
    )
    rows_text = html_doc.split("<tbody>")[1].split("</tbody>")[0]
    amp_row, slash_row = rows_text.split("</tr>")[0] + "</tr>", rows_text.split("</tr>")[1] + "</tr>"
    assert 'data-ext="1"' in amp_row and '<td title="">1</td>' in amp_row  # Ext column shows 1, not 0
    assert 'data-ext="0"' in slash_row and '<td title="1G40">0</td>' in slash_row  # Ext column shows 0, not 1
