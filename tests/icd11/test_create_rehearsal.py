"""Offline rehearsal of the create flow for a new Source: build -> load -> export -> verify.

Not evidence about a real OCL server: it proves that the build and the verifier agree. The real
evidence comes from loading the artifact into a local OCL instance (tests/README.md).
"""

from __future__ import annotations

import json
import zipfile

from ocl_pipeline_loader import load
import ocl_verify_update

main = load("who/icd-11", "cli").main


def export_as_the_server_would_return(lines: list[dict]) -> dict[str, dict]:
    """A loaded Source: the artifact's concepts, plus server-side bookkeeping the verifier must ignore."""
    return {line["id"]: {**line, "uuid": "server-only", "version": "HEAD"} for line in lines}


def write_export(path, concepts):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("export.json", json.dumps({"concepts": list(concepts.values())}))
    return path


def build(tmp_path, source):
    assert main(["build", "--input", str(source), "--output-dir", str(tmp_path / "output")]) == 0
    text = (tmp_path / "output" / "bulkimport_bundle.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def verify(tmp_path, concepts):
    return ocl_verify_update.main([
        "--mode", "create", "--owner", "WHO", "--source", "ICD-11-WHO",
        "--after", str(write_export(tmp_path / "after.zip", concepts)),
        "--artifact", str(tmp_path / "output" / "bulkimport_icd11-who.bundle.zip"),
    ])


def test_a_faithful_load_passes(tmp_path, ordered_txt):
    lines = build(tmp_path, ordered_txt)
    assert verify(tmp_path, export_as_the_server_would_return(lines)) == 0


def test_a_partial_load_is_caught(tmp_path, ordered_txt):
    lines = build(tmp_path, ordered_txt)
    concepts = export_as_the_server_would_return(lines)
    del concepts["1A03.0"]
    assert verify(tmp_path, concepts) == 1


def test_a_load_that_altered_a_name_or_added_a_concept_is_caught(tmp_path, ordered_txt):
    lines = build(tmp_path, ordered_txt)
    concepts = export_as_the_server_would_return(lines)
    concepts["1A00"]["names"][0] = {**concepts["1A00"]["names"][0], "name": "Cholera (edited)"}
    concepts["ZZ99"] = {**concepts["1A00"], "id": "ZZ99"}
    assert verify(tmp_path, concepts) == 1
