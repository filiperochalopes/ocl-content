"""FY27 ICD-10-CM XML/order reader and projection requirements."""

from __future__ import annotations

from ocl_pipeline_loader import load

reader = load("us-nchs/icd-10-cm", "release")
builder = load("us-nchs/icd-10-cm", "build_bulkimport")


def test_reads_the_xml_tabular_hierarchy_and_the_separate_order_member(fy27_zip):
    release = reader.read(fy27_zip)
    assert release.version == "2027"
    assert release.tabular_member.endswith("icd10cm-tabular_-2027.xml")
    assert release.order_member.endswith("icd10cm-order-2027.txt")
    assert set(release.nodes) == {"A00-B99", "A00-A99", "A00-A09", "A00", "A00.0", "B10", "S00-T88", "S00-S59", "S52-S59", "S52.521"}
    assert release.nodes["A00-A99"].parent == "A00-B99"
    assert release.nodes["A00-A09"].parent == "A00-A99"
    assert release.nodes["A00"].parent == "A00-A09"
    assert release.nodes["A00.0"].parent == "A00"
    assert "B10" in release.nodes and release.nodes["B10"].parent == "A00-B99"
    assert release.nodes["S52-S59"].parent == "S00-S59"
    assert sum(node.kind == "section" for node in release.nodes.values()) == 4


def test_order_codes_are_dotted_and_keep_submission_flags(fy27_zip):
    release = reader.read(fy27_zip)
    a000 = release.codes["A00.0"]
    extension = release.codes["S52.521A"]
    assert a000.order_number == 2 and a000.valid_for_submission is True
    assert a000.short_description == "Cholera due to Vibrio"
    assert extension.order_number == 5 and extension.valid_for_submission is True


def test_extension_code_absent_from_xml_falls_back_to_its_explicit_stem(fy27_zip):
    release = reader.read(fy27_zip)
    assert release.codes["S52.521A"].parent == "S52.521"


def test_build_matches_staging_topology_conventions(fy27_zip):
    result = builder.build(reader.read(fy27_zip))
    lines = {line["id"]: line for line in result.lines}
    assert lines["ICD-10-CM"]["concept_class"] == "Root"
    assert lines["A00-B99"]["concept_class"] == "Chapter"
    assert lines["A00-A09"]["concept_class"] == "Section"
    assert lines["A00"]["concept_class"] == "Diagnosis"
    assert lines["ICD-10-CM"]["names"][0]["name"] == "ICD-10-CM TABULAR LIST of DISEASES and INJURIES"
    assert lines["A00-B99"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/ICD-10-CM/"]
    assert lines["A00-A99"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/A00-B99/"]
    assert lines["A00-A09"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/A00-A99/"]
    assert lines["A00"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/A00-A09/"]
    assert lines["S52-S59"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/S00-S59/"]
    assert lines["S52.521A"]["parent_concept_urls"] == ["/orgs/US-NCHS/sources/ICD-10-CM/concepts/S52.521/"]


def test_build_exposes_order_and_leaf_metadata_without_unofficial_cuis(fy27_zip):
    result = builder.build(reader.read(fy27_zip))
    lines = {line["id"]: line for line in result.lines}
    assert lines["A00.0"]["extras"] == {"Order number": 2, "Valid for submission": True, "Leaf Node": True}
    assert lines["A00"]["extras"]["Order number"] == 1 and lines["A00"]["extras"]["Leaf Node"] is False
    assert "CUI" not in lines["A00.0"]["extras"]


def test_instruction_lists_are_regenerated_from_the_xml_with_official_names(fy27_zip):
    lines = {line["id"]: line for line in builder.build(reader.read(fy27_zip)).lines}
    # list per <note>, document order, whitespace collapsed, official XML element names (no upper-case legacy labels)
    assert lines["A00"]["extras"]["excludes1"] == ["carrier of cholera (Z22.0)", "cholera NOS (A00.9)"]
    assert lines["A00"]["extras"]["useAdditionalCode"] == ["code to identify resistance (Z16.-)"]
    assert lines["A00-B99"]["extras"]["notes"] == ["Chapter note."]
    assert lines["A00-A99"]["extras"]["notes"] == ["Applies to the contained sections."]
    assert not {"EXCLUDES1", "EXCLUDES2", "USE ADDITIONAL", "CODE FIRST", "CODE ALSO", "Note"} & {k for l in lines.values() for k in l["extras"]}
    assert "excludes1" not in lines["A00.0"]["extras"]


def test_wrapper_section_instructions_merge_into_the_same_code_diagnosis(fy27_zip):
    release = reader.read(fy27_zip)
    lines = {line["id"]: line for line in builder.build(release).lines}
    assert release.merged_section_wrappers == ["B10"]
    assert lines["B10"]["extras"]["notes"] == ["Wrapper note."] and lines["B10"]["extras"]["excludes2"] == ["herpes simplex (B00.-)"]


def test_seventh_character_note_and_definition_become_one_description(fy27_zip):
    release = reader.read(fy27_zip)
    result = builder.build(release)
    lines = {line["id"]: line for line in result.lines}
    [description] = lines["S52.521"]["descriptions"]
    # the order file has only S52.521A: exactly one concrete code for A gets an example, D (no code) does not; the <note> inside sevenChrDef follows the extension it qualifies
    assert description["description"] == "The appropriate 7th character is to be added.; A - initial encounter (S52.521A); initial encounter NOS; D - subsequent encounter"
    assert description["description_type"] == "Seventh Character" and description["locale"] == "en"
    assert "descriptions" not in lines["A00"] and "descriptions" not in lines["S52.521A"]
    assert "\n" not in description["description"]  # descriptions take ; separators, not newlines
    assert result.stats["seventh_character_inline_notes"] == {"S52.521": ["initial encounter NOS"]}
    assert result.stats["seventh_character_descriptions"] == 1
    assert result.stats["seventh_character_descriptions_with_code_examples"] == 1
    assert result.stats["instruction_concepts"]["excludes1"] == 1
