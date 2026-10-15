"""WHOCC ATC/DDD Index update projection for a populated WHOATC Source."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ocl_pipeline_loader import load


who_update = load("who/atc", "who_update")


def concept(concept_id: str, *, retired: bool = False, concept_class: str = "Code") -> dict:
    return {
        "type": "Concept",
        "id": concept_id,
        "owner": "WHO",
        "owner_type": "Organization",
        "source": "WHOATC",
        "retired": retired,
        "concept_class": concept_class,
        "datatype": "None",
        "names": [{"name": f"legacy {concept_id}", "locale": "en", "locale_preferred": True}],
        "descriptions": [{"description": "legacy UMLS note", "locale": "en", "type": "Note"}],
        "extras": {"CUI": "C123", "legacy": "remove"},
    }


def mapping(mapping_id: str, *, retired: bool = False) -> dict:
    return {
        "type": "Mapping",
        "id": mapping_id,
        "owner": "WHO",
        "owner_type": "Organization",
        "source": "WHOATC",
        "retired": retired,
        "map_type": "REPLACED BY",
        "from_concept_url": "/orgs/WHO/sources/WHOATC/concepts/A/",
        "to_concept_url": "/orgs/WHO/sources/WHOATC/concepts/A01/",
    }


def test_projects_who_records_and_retires_local_concepts_and_mappings():
    snapshot = {
        "metadata": {"who_source": "https://atcddd.fhi.no/atc_ddd_index/", "who_last_updated": "2099-01-20"},
        "records": [
            {"code": "A", "title": "WHO chapter", "level": 1, "parent": None},
            {"code": "A01", "title": "WHO group", "level": 2, "parent": "A"},
            {"code": "B", "title": "WHO new chapter", "level": 1, "parent": None},
        ],
    }
    export = {
        "concepts": [
            concept("Root", concept_class="Root"),
            concept("A"),
            concept("A01", retired=True),
            concept("Z99", concept_class="Misc"),
        ],
        "mappings": [mapping("retire-me"), mapping("already-retired", retired=True)],
    }

    result = who_update.build(snapshot, export)

    assert [(line["type"], line["id"], line.get("__action")) for line in result.lines] == [
        ("Concept", "Root", None),
        ("Concept", "A", None),
        ("Concept", "B", None),
        ("Concept", "A01", None),
        ("Mapping", "retire-me", "DELETE"),
        ("Concept", "Z99", "DELETE"),
    ]
    by_id = {line["id"]: line for line in result.lines}
    assert by_id["A"]["names"] == [
        {"name": "WHO chapter", "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}
    ]
    assert by_id["A"]["descriptions"] == []
    assert by_id["A"]["extras"] == {"ATC Level": 1, "Is_Drug_Class": "Y"}
    assert by_id["A01"]["retired"] is False
    assert by_id["B"]["parent_concept_urls"] == ["/orgs/WHO/sources/WHOATC/concepts/Root/"]
    assert by_id["retire-me"] == {
        "type": "Mapping",
        "id": "retire-me",
        "owner": "WHO",
        "owner_type": "Organization",
        "source": "WHOATC",
        "map_type": "REPLACED BY",
        "from_concept_url": "/orgs/WHO/sources/WHOATC/concepts/A/",
        "to_concept_url": "/orgs/WHO/sources/WHOATC/concepts/A01/",
        "__action": "DELETE",
    }
    assert by_id["Z99"]["concept_class"] == "Misc"
    assert result.stats == {
        "active_concepts_updated": 2,
        "retired_concepts_reactivated": 1,
        "concepts_created": 1,
        "concepts_retired": 1,
        "active_mappings_retired": 1,
        "already_retired_mappings_ignored": 1,
    }



def test_mapping_delete_does_not_require_a_target_concept_url():
    snapshot = {
        "records": [{"code": "A", "title": "WHO chapter", "level": 1, "parent": None}],
    }
    missing_target = mapping("to-source-only")
    del missing_target["to_concept_url"]
    export = {
        "concepts": [concept("Root", concept_class="Root"), concept("A")],
        "mappings": [missing_target],
    }

    result = who_update.build(snapshot, export)

    deleted = next(line for line in result.lines if line["type"] == "Mapping")
    assert deleted["id"] == "to-source-only"
    assert "to_concept_url" not in deleted


def test_cli_builds_local_update_bundle_from_who_snapshot_and_export(tmp_path):
    snapshot = {
        "metadata": {"who_source": "https://atcddd.fhi.no/atc_ddd_index/", "who_last_updated": "2099-01-20"},
        "counts": {"total": 1},
        "records": [{"code": "A", "title": "WHO chapter", "level": 1, "parent": None}],
    }
    export = {
        "owner": "WHO",
        "source": {},
        "short_code": "WHOATC",
        "concepts": [concept("Root", concept_class="Root"), concept("A"), concept("Z99", concept_class="Misc")],
        "mappings": [mapping("retire-me")],
    }
    snapshot_path = tmp_path / "who.json"
    export_path = tmp_path / "before.json"
    output_dir = tmp_path / "build"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    export_path.write_text(json.dumps(export), encoding="utf-8")

    cli = load("who/atc", "cli")
    assert cli.main([
        "build-who-update", "--snapshot", str(snapshot_path), "--export", str(export_path),
        "--output-dir", str(output_dir),
    ]) == 0

    audit = json.loads((output_dir / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["mode"] == "full-source-update"
    assert audit["upload_ready"]["local"]["status"] is True
    assert audit["changes"] == {
        "active_concepts_updated": 2,
        "retired_concepts_reactivated": 0,
        "concepts_created": 0,
        "concepts_retired": 1,
        "active_mappings_retired": 1,
        "already_retired_mappings_ignored": 0,
    }
    with zipfile.ZipFile(output_dir / "bulkimport_whoatc.local.bundle.zip") as archive:
        assert archive.namelist() == ["bulkimport_bundle.ndjson"]
        lines = [json.loads(line) for line in archive.read("bulkimport_bundle.ndjson").decode("utf-8").splitlines()]
    assert [(line["type"], line["id"], line.get("__action")) for line in lines] == [
        ("Concept", "Root", None),
        ("Concept", "A", None),
        ("Mapping", "retire-me", "DELETE"),
        ("Concept", "Z99", "DELETE"),
    ]
