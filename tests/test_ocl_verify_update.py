"""tools/ocl_verify_update.py: an update is correct only if it changed exactly what the artifact proposed."""

from __future__ import annotations

import copy
import json
import zipfile

import pytest

import ocl_verify_update as subject

EN = {"name": "Cholera", "locale": "en", "locale_preferred": True, "name_type": "Fully Specified"}
PT = {"name": "Cólera", "locale": "pt_BR", "locale_preferred": True, "name_type": "Fully Specified", "retired": False}
FR = {"name": "Choléra", "locale": "fr", "locale_preferred": True, "name_type": "Fully Specified", "retired": False}


def concept(concept_id, names, extras=None, descriptions=None, **extra):
    return {"type": "Concept", "id": concept_id, "owner": "WHO", "source": "ICD-10-WHO", "concept_class": "Code",
            "names": names, "descriptions": descriptions or [], "extras": extras or {"hierarchy_level": "3"}, **extra}


@pytest.fixture
def world():
    before = {"A00": concept("A00", [EN]), "A01": concept("A01", [{**EN, "name": "Typhoid"}]), "B00": concept("B00", [{**EN, "name": "Herpes"}])}
    after = copy.deepcopy(before)
    after["A00"]["names"] = [EN, PT, FR]
    artifact = [concept("A00", [EN, PT, FR])]
    return before, after, artifact


def failing(checks):
    return {c.id for c in checks if c.status == "fail"}


def test_the_expected_update_passes_every_check(world):
    checks = subject.verify(*world)
    assert failing(checks) == set()
    additions = next(c for c in checks if c.id == "additions-match-artifact")
    assert additions.info["added_names_by_locale"] == {"fr": 1, "pt_BR": 1}


def test_a_removed_name_is_caught(world):
    before, after, artifact = world
    after["A00"]["names"] = [PT, FR]
    assert "existing-names-kept" in failing(subject.verify(before, after, artifact))


def test_a_name_that_was_not_proposed_is_caught(world):
    before, after, artifact = world
    after["A00"]["names"].append({**PT, "name": "Cólera asiática"})
    assert "additions-match-artifact" in failing(subject.verify(before, after, artifact))


def test_a_missing_proposed_name_is_caught(world):
    before, after, artifact = world
    after["A00"]["names"] = [EN, PT]
    assert "additions-match-artifact" in failing(subject.verify(before, after, artifact))


@pytest.mark.parametrize("bad", [
    {**PT, "name_type": "Synonym"}, {**PT, "locale_preferred": False}, {**PT, "retired": True},
])
def test_an_added_name_that_breaks_the_policy_is_caught(world, bad):
    before, after, artifact = world
    after["A00"]["names"] = [EN, bad, FR]
    artifact[0]["names"] = [EN, bad, FR]
    assert "additions-policy" in failing(subject.verify(before, after, artifact))


def test_an_unexpected_locale_is_caught(world):
    before, after, artifact = world
    es = {**PT, "name": "Cólera", "locale": "es"}
    after["A00"]["names"] = [EN, es, FR]
    artifact[0]["names"] = [EN, es, FR]
    assert "additions-policy" in failing(subject.verify(before, after, artifact))
    assert "additions-policy" not in failing(subject.verify(before, after, artifact, locales=("es", "fr")))


def test_changed_extras_descriptions_and_scalars_are_caught(world):
    before, after, artifact = world
    after["A00"]["extras"] = {"hierarchy_level": "4"}
    after["A00"]["descriptions"] = [{"description": "x", "locale": "en"}]
    after["A00"]["concept_class"] = "Block"
    failed = failing(subject.verify(before, after, artifact))
    assert {"extras-unchanged", "descriptions-unchanged", "class-and-retired-unchanged"} <= failed


def test_a_collateral_change_to_an_untargeted_concept_is_caught(world):
    before, after, artifact = world
    after["B00"]["names"].append({**PT, "name": "Herpes (pt)"})
    assert failing(subject.verify(before, after, artifact)) == {"untouched-concepts-identical"}


def test_a_lost_untargeted_concept_and_a_created_concept_are_caught(world):
    before, after, artifact = world
    del after["B00"]
    after["Z99"] = concept("Z99", [EN])
    assert failing(subject.verify(before, after, artifact)) == {"untouched-concepts-identical", "no-concept-created"}


def test_a_target_absent_before_or_after_is_caught(world):
    before, after, artifact = world
    del before["A00"], after["A00"]
    assert {"targets-present-before", "targets-present-after"} <= failing(subject.verify(before, after, artifact))


def test_server_bookkeeping_fields_are_ignored(world):
    before, after, artifact = world
    after["A00"]["names"] = [{**n, "uuid": "u1", "checksum": "c"} for n in after["A00"]["names"]]
    after["A01"]["version"] = "v2"
    assert failing(subject.verify(before, after, artifact)) == set()


def write_zip(path, concepts):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export.json", json.dumps({"concepts": list(concepts.values())}))
    return path


def test_cli_passes_writes_a_deterministic_report_and_exits_zero(world, tmp_path, capsys):
    before, after, artifact = world
    bundle = tmp_path / "bundle.ndjson"
    bundle.write_text("\n".join(json.dumps(line) for line in artifact) + "\n", encoding="utf-8")
    args = ["--before", str(write_zip(tmp_path / "before.zip", before)), "--after", str(write_zip(tmp_path / "after.zip", after)),
            "--artifact", str(bundle), "--report"]
    assert subject.main([*args, str(tmp_path / "r1.json")]) == 0
    assert subject.main([*args, str(tmp_path / "r2.json")]) == 0
    first = (tmp_path / "r1.json").read_text(encoding="utf-8")
    assert first == (tmp_path / "r2.json").read_text(encoding="utf-8")
    report = json.loads(first)
    assert report["result"] == "pass" and report["inputs"]["before"]["file"] == "before.zip"
    assert str(tmp_path) not in first and "generated_at" not in first
    assert "result: PASS" in capsys.readouterr().out


def test_cli_exits_nonzero_when_a_check_fails(world, tmp_path, capsys):
    before, after, artifact = world
    after["B00"]["names"].append(PT)
    bundle = tmp_path / "bundle.ndjson"
    bundle.write_text(json.dumps(artifact[0]) + "\n", encoding="utf-8")
    code = subject.main(["--before", str(write_zip(tmp_path / "b.zip", before)), "--after", str(write_zip(tmp_path / "a.zip", after)),
                         "--artifact", str(bundle)])
    assert code == 1 and "result: FAIL" in capsys.readouterr().out


def test_artifact_can_be_a_zip_with_the_bundle_or_a_directory_of_parts(world, tmp_path):
    _, _, artifact = world
    text = "\n".join(json.dumps(line) for line in artifact) + "\n"
    archive = tmp_path / "bulk.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("bulkimport_bundle.ndjson", text)
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "bulkimport_part_001.ndjson").write_text(text, encoding="utf-8")
    assert subject.read_artifact(archive) == subject.read_artifact(parts) == artifact


def test_audit_must_name_the_before_export(world, tmp_path):
    before, _, _ = world
    path = write_zip(tmp_path / "before.zip", before)
    import ocl_export

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"export": {"sha256": ocl_export.sha256_path(path)}}), encoding="utf-8")
    assert subject.audit_check(good, path).status == "pass"
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"export": {"sha256": "0" * 64}}), encoding="utf-8")
    assert subject.audit_check(stale, path).status == "fail"
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"export": None}), encoding="utf-8")
    assert "offline baseline" in subject.audit_check(draft, path).examples[0]


def test_the_verifier_reads_files_only():
    source = (subject.__file__ and open(subject.__file__, encoding="utf-8").read())
    for marker in ("urllib", "requests", "socket", "OCL_API_TOKEN"):
        assert marker not in source


# --- create mode (a brand-new Source) and the replica-fidelity use of an empty artifact ---------------

def test_create_mode_passes_when_the_source_equals_the_artifact(world):
    _, after, artifact = world
    artifact = [concept(cid, c["names"], c["extras"]) for cid, c in after.items()]
    assert failing(subject.verify_creation(after, artifact)) == set()


def test_create_mode_catches_missing_changed_and_extra_concepts(world):
    _, after, _ = world
    artifact = [concept(cid, c["names"], c["extras"]) for cid, c in after.items()]
    broken = copy.deepcopy(after)
    del broken["A01"]
    broken["B00"]["names"][0]["name"] = "Different"
    broken["A00"]["extras"] = {"hierarchy_level": "9"}
    broken["Z99"] = concept("Z99", [EN])
    assert failing(subject.verify_creation(broken, artifact)) == {
        "all-concepts-loaded", "names-match-artifact", "extras-match-artifact", "no-concept-beyond-artifact",
    }


def test_cli_create_mode_needs_no_before_export(world, tmp_path):
    _, after, _ = world
    artifact = [concept(cid, c["names"], c["extras"]) for cid, c in after.items()]
    bundle = tmp_path / "bundle.ndjson"
    bundle.write_text("\n".join(json.dumps(line) for line in artifact) + "\n", encoding="utf-8")
    code = subject.main(["--mode", "create", "--after", str(write_zip(tmp_path / "after.zip", after)),
                         "--artifact", str(bundle), "--report", str(tmp_path / "r.json")])
    assert code == 0 and json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["target"]["mode"] == "create"


def test_update_mode_requires_a_before_export(world, tmp_path, capsys):
    _, after, _ = world
    bundle = tmp_path / "bundle.ndjson"
    bundle.write_text("", encoding="utf-8")
    assert subject.main(["--after", str(write_zip(tmp_path / "after.zip", after)), "--artifact", str(bundle)]) == 2
    assert "--before is required" in capsys.readouterr().err


def test_an_empty_artifact_turns_update_mode_into_a_replica_fidelity_check(world, tmp_path):
    """Seeding a local replica from production: no concept is targeted, so every one must be identical."""
    before, after, _ = world
    empty = tmp_path / "empty.ndjson"
    empty.write_text("", encoding="utf-8")
    args = ["--artifact", str(empty)]
    same = ["--before", str(write_zip(tmp_path / "prod.zip", before)), "--after", str(write_zip(tmp_path / "replica.zip", before))]
    assert subject.main([*same, *args]) == 0
    drifted = ["--before", str(write_zip(tmp_path / "prod2.zip", before)), "--after", str(write_zip(tmp_path / "replica2.zip", after))]
    assert subject.main([*drifted, *args]) == 1
