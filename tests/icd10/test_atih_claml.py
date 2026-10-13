"""ATIH CIM-10-FR ClaML adapter: variant selection, chapters, references, modifier classes."""

from __future__ import annotations

import pytest

from ocl_pipeline_loader import load
atih_claml = load("who/icd-10", "adapters.atih_claml")
NameCandidate = load("who/icd-10", "model").NameCandidate


def _by_code(atih_xml) -> dict[str, NameCandidate]:
    result = atih_claml.candidates(atih_xml)
    return {candidate.code: candidate for candidate in result.candidates}


def test_uses_who_label_when_both_variants_exist(atih_xml):
    candidate = _by_code(atih_xml)["U07.1"]
    assert candidate.label == "COVID-19, virus identifié"
    assert candidate.variant == "OMS"
    assert "variant-OMS" in candidate.flags
    assert "variant-selected-from-multiple" in candidate.flags


def test_inline_reference_is_not_part_of_the_name(atih_xml):
    candidate = _by_code(atih_xml)["A06.4"]
    assert candidate.label == "Abcès amibien du foie"
    assert "K77.0" not in candidate.label
    assert "inline-markup" in candidate.flags


def test_chapter_numeral_is_converted_and_flagged(atih_xml):
    candidate = _by_code(atih_xml)["22"]
    assert candidate.source_code == "XXII"
    assert "chapter-roman-normalized" in candidate.flags


def test_inclusion_rubrics_are_not_emitted_as_names(atih_xml):
    labels = {candidate.label for candidate in atih_claml.candidates(atih_xml).candidates}
    assert "Choléra classique" not in labels


def test_ambiguous_preferred_labels_without_who_variant_are_skipped(atih_xml):
    result = atih_claml.candidates(atih_xml)
    assert all(candidate.code != "M34" for candidate in result.candidates)
    assert {"reason": "conflicting-preferred-labels-without-OMS", "source_code": "M34", "kind": "category"} in result.skipped


def test_modifier_classes_are_counted_and_skipped(atih_xml):
    result = atih_claml.candidates(atih_xml)
    assert result.stats["modifier_classes"] == 1
    assert {"reason": "modifier-class", "source_code": "0"} in result.skipped


def test_declared_edition_and_lang_are_recorded(atih_xml):
    stats = atih_claml.candidates(atih_xml).stats
    assert stats["declared_lang"] == "fr"
    assert stats["title"]["version"] == "2024"
    assert stats["kinds"]["chapter"] == 2


def test_external_doctype_is_accepted_and_internal_entities_are_refused(tmp_path):
    external = tmp_path / "external-doctype.xml"
    external.write_text(
        '<?xml version="1.0"?><!DOCTYPE ClaML SYSTEM "ClaML.dtd"><ClaML version="2.0.0">'
        '<Class code="A00" kind="category"><Rubric kind="preferred"><Label xml:lang="fr">Choléra</Label>'
        "</Rubric></Class></ClaML>",
        encoding="utf-8",
    )
    assert [candidate.label for candidate in atih_claml.candidates(external).candidates] == ["Choléra"]

    internal = tmp_path / "internal-entities.xml"
    internal.write_text(
        '<?xml version="1.0"?><!DOCTYPE ClaML [<!ENTITY cross "&#8224;">]><ClaML version="2.0.0"/>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="internal DTD subset or entity"):
        atih_claml.candidates(internal)


def test_non_claml_root_is_refused(tmp_path):
    path = tmp_path / "not-claml.xml"
    path.write_text('<?xml version="1.0"?><cid10 versao="V2007"/>', encoding="utf-8")
    with pytest.raises(ValueError, match="expected a ClaML root"):
        atih_claml.candidates(path)
