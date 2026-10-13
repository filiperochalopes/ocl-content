"""Tests for the WHO-ATC Turtle reader."""

from __future__ import annotations

from ocl_pipeline_loader import load

ttl_reader = load("who/atc", "ttl_reader")


def test_reads_version_and_source(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    assert ontology.version_info == "2099_01_01"
    assert ontology.umls_source == "UMLS 2099AB"


def test_skips_semantic_type_classes(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    assert ontology.skipped_semantic_types == 2
    assert all(not entry.code.startswith("T1") for entry in ontology.classes)


def test_reads_every_atc_class(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    codes = {entry.code for entry in ontology.classes}
    assert codes == {"A", "A01", "A01A", "A01AD", "A01AD02"}
    assert ontology.duplicate_codes == []


def test_level_1_has_no_parent_and_altlabel(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    chapter = next(entry for entry in ontology.classes if entry.code == "A")
    assert chapter.level == 1
    assert chapter.parent is None
    assert chapter.title == "ALIMENTARY TRACT AND METABOLISM DRUGS"
    assert chapter.alt_label == "ALIMENTARY TRACT AND METABOLISM"
    assert chapter.is_drug_class == "Y"
    assert chapter.cui == "C3653992"
    assert chapter.semantic_types == ("T121",)


def test_subclass_chain_parents(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    by_code = {entry.code: entry for entry in ontology.classes}
    assert by_code["A01"].parent == "A"
    assert by_code["A01A"].parent == "A01"
    assert by_code["A01AD"].parent == "A01A"
    assert by_code["A01AD02"].parent == "A01AD"


def test_level_5_has_no_is_drug_class_predicate(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    leaf = next(entry for entry in ontology.classes if entry.code == "A01AD02")
    assert leaf.level == 5
    assert leaf.is_drug_class is None  # absent in the source file, same as the live export
    assert leaf.semantic_types == ("T121", "T109")


def test_missing_file_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        ttl_reader.read(tmp_path / "missing.ttl")


def test_duplicate_code_is_recorded(tmp_path):
    text = (
        '@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n'
        '<http://purl.bioontology.org/ontology/ATC/> a owl:Class ; owl:versionInfo "2099_01_01" .\n\n'
        '<http://purl.bioontology.org/ontology/ATC/A> a owl:Class ;\n'
        '\tskos:prefLabel """First"""@en ;\n'
        '\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """1"""^^xsd:string ;\n'
        '\trdfs:subClassOf owl:Thing ;\n .\n\n'
        '<http://purl.bioontology.org/ontology/ATC/A> a owl:Class ;\n'
        '\tskos:prefLabel """Second"""@en ;\n'
        '\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """1"""^^xsd:string ;\n'
        '\trdfs:subClassOf owl:Thing ;\n .\n'
    )
    path = tmp_path / "dup.ttl"
    path.write_text(text, encoding="utf-8")
    ontology = ttl_reader.read(path)
    assert ontology.duplicate_codes == ["A"]
