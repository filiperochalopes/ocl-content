"""DATASUS XML adapter: entity handling, structure walking, and code normalization."""

from __future__ import annotations

import zipfile

import pytest

from pipeline.adapters import datasus_xml
from pipeline.model import NameCandidate


def _by_code(source) -> dict[str, NameCandidate]:
    return {candidate.code: candidate for candidate in datasus_xml.candidates(source).candidates}


def test_reads_the_archive_and_normalizes_codes(datasus_xml_zip):
    result = datasus_xml.candidates(datasus_xml_zip)
    codes = set(_by_code(datasus_xml_zip))
    assert {"1", "A00-A09", "A00", "A00.0", "A00.9", "A06"} <= codes
    assert result.stats["versions"] == "V2007"
    assert result.stats["counts"] == {"chapter": 1, "group": 1, "category": 2, "subcategory": 2}
    assert result.stats["out_of_scope_members"] == ["CID-O.xml"]
    assert all(candidate.authority == "DATASUS" for candidate in result.candidates)


def test_latin1_and_dtd_entities_are_resolved(datasus_xml_zip):
    by_code = _by_code(datasus_xml_zip)
    assert by_code["A00.0"].label == "Cólera devida a Vibrio cholerae 01, biótipo cholerae"
    assert by_code["A06"].label == "Abscesso hepático † amebiano"


def test_directory_input_matches_archive_input(datasus_xml_dir, datasus_xml_zip):
    assert {candidate.code for candidate in datasus_xml.candidates(datasus_xml_dir).candidates} == set(_by_code(datasus_xml_zip))


def test_reference_and_restriction_content_is_not_a_name(datasus_xml_zip):
    labels = {candidate.label for candidate in datasus_xml.candidates(datasus_xml_zip).candidates}
    assert not any("J99.8" in label for label in labels)


def test_undeclared_entity_is_refused(tmp_path):
    path = tmp_path / "CID10XML.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CID10.xml", '<cid10 versao="V2007"><capitulo numcap="1"><nome>Umlaut &auml;</nome></capitulo></cid10>')
        archive.writestr("CID10.dtd", '<!ENTITY cruz "&#8224;">')
    with pytest.raises(ValueError, match="not declared by the shipped DTD: &auml;"):
        datasus_xml.candidates(path)


def test_external_entity_declaration_is_refused(tmp_path):
    path = tmp_path / "CID10XML.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CID10.xml", '<cid10 versao="V2007"><capitulo numcap="1"><nome>x</nome></capitulo></cid10>')
        archive.writestr("CID10.dtd", '<!ENTITY remote SYSTEM "http://example.org/ent">')
    with pytest.raises(ValueError, match="refusing external entity declaration"):
        datasus_xml.candidates(path)


def test_non_cid10_root_is_refused(tmp_path):
    path = tmp_path / "CID10XML.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CID10.xml", "<document/>")
    with pytest.raises(ValueError, match="expected a cid10 root element"):
        datasus_xml.candidates(path)


def test_archive_without_the_xml_is_refused(tmp_path):
    path = tmp_path / "CID10XML.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "nothing here")
    with pytest.raises(ValueError, match="no CID10.xml inside the archive"):
        datasus_xml.candidates(path)
