"""Tests for the WHO-ATC retirement-only update projection."""

from __future__ import annotations

from ocl_pipeline_loader import load

ttl_reader = load("who/atc", "ttl_reader")
retirements = load("who/atc", "retirements")


def concept(concept_id: str, *, retired: bool = False) -> dict:
    return {
        "type": "Concept", "id": concept_id, "owner": "WHO", "owner_type": "Organization", "source": "WHOATC",
        "concept_class": "Code", "datatype": "None", "retired": retired,
        "names": [{"type": "ConceptName", "name": f"Name {concept_id}", "locale": "en", "locale_preferred": True,
                   "name_type": "Fully Specified", "retired": False, "external_id": None, "uuid": "ignore"}],
        "descriptions": [{"type": "ConceptDescription", "description": f"Description {concept_id}", "locale": "en",
                          "locale_preferred": True, "description_type": "Note", "retired": False, "uuid": "ignore"}],
        "extras": {"ATC Level": "5"},
    }


def test_only_active_snapshot_codes_absent_from_the_ontology_are_retired(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    snapshot = {
        "A": concept("A"),              # current upstream code: unchanged
        "T001": concept("T001"),        # active source-only code: retire
        "T002": concept("T002", retired=True),  # already retired: no update
        "Root": concept("Root"),        # synthetic root: never retire
    }
    result = retirements.build(ontology, snapshot)
    assert result.candidate_ids == ["T001"]
    assert result.ignored_already_retired == ["T002"]
    assert result.before[0]["retired"] is False
    assert result.after[0]["retired"] is True


def test_before_and_after_preserve_collections_and_change_only_concept_retired(ttl_path):
    result = retirements.build(ttl_reader.read(ttl_path), {"T001": concept("T001")})
    before, after = result.before[0], result.after[0]
    assert before["id"] == after["id"] == "T001"
    assert before["names"] == after["names"]
    assert before["descriptions"] == after["descriptions"]
    assert before["extras"] == after["extras"]
    assert before["retired"] is False and after["retired"] is True
    assert set(after) == {"type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired", "names", "descriptions", "extras"}


def test_projection_converts_api_description_type_to_import_type(ttl_path):
    result = retirements.build(ttl_reader.read(ttl_path), {"T001": concept("T001")})
    description = result.after[0]["descriptions"][0]
    assert description["type"] == "Note"
    assert "description_type" not in description
    assert "uuid" not in description


def test_no_mapping_is_possible_in_the_retirement_projection(ttl_path):
    result = retirements.build(ttl_reader.read(ttl_path), {"T001": concept("T001")})
    assert all(line["type"] == "Concept" for line in result.after)
    assert all("map_type" not in line for line in result.after)
