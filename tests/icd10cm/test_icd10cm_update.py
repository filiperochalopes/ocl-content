"""Update projection against a target environment's own export (ICD-10-CM FY27)."""

from __future__ import annotations

import json
import zipfile

from ocl_pipeline_loader import load

release_reader = load("us-nchs/icd-10-cm", "release")
builder = load("us-nchs/icd-10-cm", "build_bulkimport")
cli = load("us-nchs/icd-10-cm", "cli")

OWNER, SOURCE = "US-NCHS", "ICD-10-CM"


def old_concept(code, name, extras, synonyms=(), cls="Diagnosis", parent=None):
    names = [{"uuid": "1", "name": name, "external_id": None, "type": "ConceptName", "locale": "en",
              "locale_preferred": True, "name_type": "Fully Specified", "checksum": "x"}]
    names += [{"uuid": "2", "name": s, "external_id": None, "type": "ConceptName", "locale": "en",
               "locale_preferred": False, "name_type": "Synonym", "checksum": "y"} for s in synonyms]
    return {"type": "Concept", "id": code, "external_id": None, "concept_class": cls, "datatype": "None", "names": names,
            "descriptions": [], "extras": extras, "retired": False, "source": SOURCE, "owner": OWNER,
            "parent_concept_urls": [parent] if parent else []}


def build_release(fy27_zip):
    path = fy27_zip
    # the fixture writes both members into one archive; the reader accepts the same path for both inputs
    return builder.build(release_reader.read(path, path))


def test_update_preserves_what_the_release_does_not_govern(fy27_zip):
    result = build_release(fy27_zip)
    existing = {
        "A00.0": old_concept("A00.0", "Old name", {"CUI": "C1", "Semantic Types": ["T047"], "EXCLUDES1": "x", "Note": "n", "Other": "keep", "Order number": 2.0},
                             synonyms=["Cholera NOS"]),
        "T047": old_concept("T047", "Disease or Syndrome", {"Leaf Node": True}),
        "B10-B10": old_concept("B10-B10", "range", {"Leaf Node": True}),
        "A00.9": old_concept("A00.9", "removed code", {"Leaf Node": True}),
    }
    update = builder.project_update(result, existing)
    by = {line["id"]: line for line in update.lines}
    line = by["A00.0"]
    assert [n["name"] for n in line["names"]] == ["Cholera due to Vibrio cholerae", "Cholera NOS"]
    assert line["names"][1]["name_type"] == "Synonym" and set(line["names"][1]) == set(builder.NAME_KEYS)
    assert "CUI" not in line["extras"] and "Semantic Types" not in line["extras"]
    # legacy upper-case instruction extras are replaced by the XML-derived ones, never carried; unknown extras stay
    assert "EXCLUDES1" not in line["extras"] and "Note" not in line["extras"] and line["extras"]["Other"] == "keep"
    assert update.stats["legacy_instruction_extras_replaced"] == 2
    assert line["extras"]["Order number"] == 2 and line["extras"]["Valid for submission"] is True
    assert update.stats["preferred_name_changed"] == 1 and update.stats["synonyms_preserved"] == 1
    assert update.stats["created"] == len(result.lines) - 1 and update.stats["existing_updated"] == 1
    assert update.not_in_release == {"semantic_type_ids": ["T047"], "synthetic_ranges": ["B10-B10"], "other_codes": ["A00.9"]}
    assert not any("external_id" in l or any("external_id" in n for n in l.get("names", [])) for l in update.lines)


def test_update_applies_the_release_class_and_never_retires(fy27_zip):
    result = build_release(fy27_zip)
    existing = {"A00": old_concept("A00", "Cholera", {"Leaf Node": False}, cls="Diagnosis"),
                "A00-A09": old_concept("A00-A09", "Intestinal infectious diseases", {"Leaf Node": False}, cls="Diagnosis")}
    update = builder.project_update(result, existing)
    by = {l["id"]: l for l in update.lines}
    assert by["A00"]["concept_class"] == "Diagnosis" and by["A00"]["retired"] is False
    assert by["ICD-10-CM"]["concept_class"] == "Root" and by["A00-A09"]["concept_class"] == "Section"
    assert not any(l.get("__action") for l in update.lines)


def test_cli_export_requires_environment_and_writes_environment_named_bundle(fy27_zip, tmp_path, monkeypatch):
    export = tmp_path / "export.zip"
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("export.json", json.dumps({"concepts": [old_concept("A00", "Cholera", {"CUI": "C9"})]}))
    base = ["build", "--tabular", str(fy27_zip), "--order", str(fy27_zip)]
    monkeypatch.setattr(cli.assets, "verify_local", lambda *a, **k: None)
    assert cli.main(base + ["--export", str(export)]) == 1
    out = tmp_path / "out"
    assert cli.main(base + ["--export", str(export), "--environment", "staging", "--output-dir", str(out)]) == 0
    audit = json.loads((out / "bulkimport_audit.json").read_text())
    assert audit["mode"] == "source-export" and audit["environment"] == "staging"
    assert audit["upload_ready"]["staging"]["status"] is False and audit["upload_ready"]["production"]["status"] is False
    assert (out / "bulkimport_icd10cm.staging.bundle.zip").is_file()
    assert any(i["role"] == "target-export" and i["concepts"] == 1 for i in audit["inputs"])


def test_update_drops_umls_and_retires_only_semantic_type_concepts(fy27_zip):
    result = build_release(fy27_zip)
    existing = {
        "A00.0": old_concept("A00.0", "x", {"CUI": "C1", "Semantic Types": ["T047"], "EXCLUDES1": "keep"}),
        "T047": old_concept("T047", "Disease or Syndrome", {"Leaf Node": True}),
        "T191": {**old_concept("T191", "Neoplastic Process", {}), "retired": True},
        "B10-B10": old_concept("B10-B10", "range", {"Leaf Node": True}),
    }
    update = builder.project_update(result, existing)
    by = {l["id"]: l for l in update.lines}
    assert "CUI" not in by["A00.0"]["extras"] and "Semantic Types" not in by["A00.0"]["extras"]
    assert "EXCLUDES1" not in by["A00.0"]["extras"]
    deletes = [l for l in update.lines if l.get("__action")]
    assert [(l["id"], l["__action"], l["concept_class"]) for l in deletes] == [("T047", "DELETE", "Diagnosis")]
    assert update.stats["umls_extras_dropped"] == 2 and update.stats["semantic_type_concepts_retired"] == 1
    assert "B10-B10" not in {l["id"] for l in deletes}


def test_update_regenerates_instructions_and_keeps_only_foreign_descriptions(fy27_zip):
    result = build_release(fy27_zip)
    old_seventh = {"description": "stale", "locale": "en", "locale_preferred": True, "description_type": "Seventh Character"}
    other = {"description": "kept", "locale": "en", "locale_preferred": False, "description_type": "Note"}
    existing = {"A00": old_concept("A00", "Cholera", {"EXCLUDES1": "old text"}),
                "S52.521": {**old_concept("S52.521", "x", {}), "descriptions": [old_seventh, other]}}
    by = {l["id"]: l for l in builder.project_update(result, existing).lines}
    assert by["A00"]["extras"]["excludes1"] == ["carrier of cholera (Z22.0)", "cholera NOS (A00.9)"]
    assert "EXCLUDES1" not in by["A00"]["extras"]
    descriptions = by["S52.521"]["descriptions"]
    assert [d["description_type"] for d in descriptions] == ["Seventh Character", "Note"] and descriptions[0]["description"] != "stale"
    # a code the target does not hold yet is created with its instructions
    assert by["B10"]["extras"]["notes"] == ["Wrapper note."]
