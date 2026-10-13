"""Tests for the WHO/WHOATC export-alignment classifier (read-only review report)."""

from __future__ import annotations

from ocl_pipeline_loader import load

ttl_reader = load("who/atc", "ttl_reader")
align_module = load("who/atc", "align")


def export_concept(concept_id, name, *, retired=False):
    return {
        "id": concept_id,
        "retired": retired,
        "names": [{"name": name, "name_type": "Fully Specified"}],
    }


def test_unchanged_when_name_matches(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    export = {"A": export_concept("A", "ALIMENTARY TRACT AND METABOLISM DRUGS")}
    rows = align_module.align(ontology, export)
    row = next(r for r in rows if r.code == "A")
    assert row.status == align_module.STATUS_UNCHANGED


def test_listing_snapshot_avoids_a_lexical_comparison(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    # The list endpoint carries `display_name`, but not the authoritative `names` collection.
    rows = align_module.align(ontology, {"A": {"id": "A", "retired": False, "display_name": "display only"}})
    row = next(r for r in rows if r.code == "A")
    assert row.status == align_module.STATUS_PRESENT
    assert row.export_title == "display only"


def test_new_when_code_absent_from_export(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    rows = align_module.align(ontology, {})
    row = next(r for r in rows if r.code == "A")
    assert row.status == align_module.STATUS_NEW


def test_missing_candidate_when_export_has_a_code_the_ontology_does_not(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    export = {
        "A": export_concept("A", "ALIMENTARY TRACT AND METABOLISM DRUGS"),
        "Z99": export_concept("Z99", "Something retired long ago"),
    }
    rows = align_module.align(ontology, export)
    row = next(r for r in rows if r.code == "Z99")
    assert row.status == align_module.STATUS_MISSING_CANDIDATE


def test_already_retired_is_not_a_candidate(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    export = {
        "A": export_concept("A", "ALIMENTARY TRACT AND METABOLISM DRUGS"),
        "Z99": export_concept("Z99", "Already gone", retired=True),
    }
    rows = align_module.align(ontology, export)
    row = next(r for r in rows if r.code == "Z99")
    assert row.status == align_module.STATUS_ALREADY_RETIRED


def test_root_is_never_a_candidate(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    export = {"Root": export_concept("Root", "Root")}
    rows = align_module.align(ontology, export)
    assert all(row.code != "Root" for row in rows)


def test_summarize_counts_each_status(ttl_path):
    ontology = ttl_reader.read(ttl_path)
    rows = align_module.align(ontology, {})
    summary = align_module.summarize(rows)
    assert summary[align_module.STATUS_NEW] == len(ontology.classes)


def test_write_csv_round_trips(tmp_path, ttl_path):
    import csv

    ontology = ttl_reader.read(ttl_path)
    rows = align_module.align(ontology, {})
    out = tmp_path / "alignment_report.csv"
    align_module.write_csv(out, rows)
    with out.open(newline="", encoding="utf-8") as stream:
        read_rows = list(csv.DictReader(stream))
    assert len(read_rows) == len(rows)
    assert read_rows[0]["status"] == align_module.STATUS_NEW
