"""WHO ClaML canonical extraction: chapters, modifier expansion, and baseline verification."""

from __future__ import annotations

import pytest

from ocl_pipeline_loader import load
who_claml = load("icd/icd-10", "adapters.who_claml")
CanonicalConcept = load("icd/icd-10", "canonical").CanonicalConcept


def test_extracts_chapters_blocks_and_categories(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    by_id = extraction.by_id
    assert by_id["1"].id == "1"                      # roman numeral mapped to the baseline number
    assert by_id["1"].name == "Certain infectious and parasitic diseases"
    assert by_id["22"].id == "22"
    assert by_id["A00-A09"].concept_class == "Group"
    assert by_id["A00"].concept_class == "Code"
    assert extraction.stats["roman_chapters"] == 2


def test_modifier_expansion_reproduces_derived_codes_and_names(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    assert extraction.by_id["E10.0"].name == "Type 1 diabetes mellitus: With coma"
    assert extraction.by_id["E10.9"].name == "Type 1 diabetes mellitus: Without complications"
    assert extraction.stats["modifier_derived"] == 3


def test_dot_is_inserted_for_a_bare_subcode_on_a_three_character_parent(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    assert extraction.by_id["I70.0"].name == "Atherosclerosis: without gangrene"
    assert extraction.stats["modifier_derived_dot_inserted"] == 1
    assert all(entry["reason"] != "derived-code-collision" for entry in extraction.skipped)


def test_modifier_class_without_a_label_is_reported(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    assert {"reason": "modifier-label-missing", "source_code": "I70", "modifier": "I70M10_4", "subcode": "1"} in extraction.skipped
    assert "I70.1" not in extraction.by_id


def test_extraction_reports_edition_and_counts(who_claml_zip):
    stats = who_claml.extract(who_claml_zip).stats
    assert stats["declared_lang"] == "en"
    assert stats["edition"]["version"] == "2019-covid-expanded"
    assert stats["class_counts"] == {"Chapter": 2, "Code": 6, "Group": 1}


def test_internal_entities_are_refused(tmp_path):
    path = tmp_path / "who.xml"
    path.write_text('<?xml version="1.0"?><!DOCTYPE ClaML [<!ENTITY x "y">]><ClaML/>', encoding="utf-8")
    with pytest.raises(ValueError, match="internal DTD subset or entity"):
        who_claml.extract(path)


def test_verify_reports_what_each_side_has_alone(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    baseline = {
        "1": CanonicalConcept("1", "Chapter", "Certain infectious and parasitic diseases", "", {}, ""),
        "A00": CanonicalConcept("A00", "Code", "Cholera", "", {}, ""),
        "E10.0": CanonicalConcept("E10.0", "Code", "Type 1 diabetes mellitus: With coma", "", {}, ""),
        "S52.0": CanonicalConcept("S52.0", "Code", "Fracture of upper end of ulna", "", {}, ""),
        "wrong": CanonicalConcept("wrong", "Code", "Cholera", "", {}, ""),
    }
    report = who_claml.verify(extraction, baseline)
    assert report["ids_in_both"] == 3
    assert report["ids_only_in_baseline"] == ["S52.0", "wrong"]
    assert "E10.9" in report["ids_only_in_who"]
    assert report["name_mismatches"] == []
    assert report["class_mismatches"] == []


def test_verify_separates_prefix_context_renaming_from_real_differences(who_claml_zip):
    extraction = who_claml.extract(who_claml_zip)
    baseline = {
        "A00": CanonicalConcept("A00", "Code", "Malignant neoplasm: Cholera", "", {}, ""),
        "E10.0": CanonicalConcept("E10.0", "Code", "Diabetes: With coma", "", {}, ""),
    }
    report = who_claml.verify(extraction, baseline)
    assert report["name_mismatches_prefixed_context"] == 1
    assert report["name_mismatches_other"] == 1
    assert {entry["id"] for entry in report["name_mismatches"]} == {"A00", "E10.0"}
