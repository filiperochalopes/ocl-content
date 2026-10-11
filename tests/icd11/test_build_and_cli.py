"""The ICD-11 build, its artifacts, and the guarantees every pipeline here shares."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ocl_pipeline_loader import load
st = load("icd/icd-11", "simple_tabulation")
build = load("icd/icd-11", "build_bulkimport").build
ROOT_ID = load("icd/icd-11", "simple_tabulation").ROOT_ID
main = load("icd/icd-11", "cli").main

PROJECTION = {
    "type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired",
    "names", "extras", "parent_concept_urls",
}


def lines_for(path):
    return build(st.read(path)).lines


def test_root_comes_first_and_chapters_hang_under_it(ordered_txt):
    lines = lines_for(ordered_txt)
    assert lines[0]["id"] == "ICD-11-Root" and lines[0]["concept_class"] == "Root"
    chapter = next(line for line in lines if line["id"] == "Chapter-01")
    assert chapter["parent_concept_urls"] == ["/orgs/WHO/sources/ICD-11-WHO/concepts/ICD-11-Root/"]


def test_each_line_carries_the_projection_and_a_fully_specified_name(ordered_txt):
    for line in lines_for(ordered_txt)[1:]:
        assert set(line) <= PROJECTION
        assert line["owner"] == "WHO" and line["source"] == "ICD-11-WHO" and line["datatype"] == "N/A"
        assert line["names"][0]["name_type"] == "Fully Specified" and line["names"][0]["locale"] == "en"


def test_extras_drop_empty_values_and_keep_the_documented_keys(ordered_txt):
    cholera = next(line for line in lines_for(ordered_txt) if line["id"] == "1A00")
    assert cholera["extras"]["isLeaf"] == "False"
    assert cholera["extras"]["BrowserLink"].endswith("#300")
    assert "BlockId" not in cholera["extras"]


def test_concept_urls_escape_reserved_characters():
    concept_url = load("icd/icd-11", "build_bulkimport").concept_url

    assert concept_url("A/B&C") == "/orgs/WHO/sources/ICD-11-WHO/concepts/A%2FB%26C/"


def test_every_parent_precedes_its_child(ordered_txt):
    lines = lines_for(ordered_txt)
    seen = set()
    for line in lines:
        for url in line.get("parent_concept_urls", []):
            assert url.rstrip("/").rsplit("/", 1)[1] in seen | {ROOT_ID}, line["id"]
        seen.add(line["id"])


def test_a_parent_that_comes_later_is_refused(tabulation_txt):
    tabulation = st.read(tabulation_txt)
    # In the synthetic file '600' precedes its parent 'XA1B2C': build refuses an order OCL cannot import.
    with pytest.raises(ValueError, match="comes later in the file"):
        build(tabulation)


def build_args(tmp_path: Path, source: Path, *extra: str) -> list[str]:
    return ["build", "--input", str(source), "--output-dir", str(tmp_path / "output"), "--max-part-size", "600b", *extra]


def test_cli_writes_ordered_capped_parts_a_bundle_an_archive_and_an_audit(tmp_path, ordered_txt):
    assert main(build_args(tmp_path, ordered_txt)) == 0
    output = tmp_path / "output"
    parts = sorted(output.glob("bulkimport_part_*.ndjson"))
    zips = sorted(output.glob("bulkimport_part_*.zip"))
    assert len(parts) > 1 and [z.stem for z in zips] == [p.stem for p in parts]
    assert all(z.stat().st_size <= 600 for z in zips)          # the cap is on the COMPRESSED upload zip
    assert b"".join(part.read_bytes() for part in parts) == (output / "bulkimport_bundle.ndjson").read_bytes()
    audit = json.loads((output / "bulkimport_audit.json").read_text(encoding="utf-8"))
    assert audit["target"] == {"owner": "WHO", "source": "ICD-11-WHO", "owner_type": "Organization"}
    assert audit["upload_ready"] is False and audit["warning"]
    assert audit["upload"] == {**audit["upload"], "mechanism": "manual", "api_upload": False}
    assert audit["inputs"][0]["release"] == "2026-01"
    with zipfile.ZipFile(output / "bulkimport_icd11-who.zip") as archive:
        assert {"bulkimport_bundle.ndjson", "bulkimport_manifest.json"} <= set(archive.namelist())


def test_rebuild_is_byte_identical_and_records_no_absolute_paths(tmp_path, ordered_txt):
    outputs = []
    for run in ("first", "second"):
        run_dir = tmp_path / run
        run_dir.mkdir()
        assert main(build_args(run_dir, ordered_txt)) == 0
        outputs.append(run_dir / "output")
    for name in ("bulkimport_audit.json", "bulkimport_icd11-who.zip", "bulkimport_bundle.ndjson"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name
    text = (outputs[0] / "bulkimport_audit.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "/Users/" not in text and "generated_at" not in text


def test_missing_input_fails_with_a_fetch_hint(tmp_path):
    assert main(build_args(tmp_path, tmp_path / "absent.zip")) == 1
    assert not (tmp_path / "output").exists()


def test_the_pinned_asset_is_the_official_2026_01_url():
    assets = load("icd/icd-11", "assets")

    asset = assets.resolve("simple-tabulation")
    assert asset.url == "https://icdcdn.who.int/static/releasefiles/2026-01/SimpleTabulation-ICD-11-MMS-en.zip"
    assert asset.sha256 == "f1356588f40953a83e3af2b662deab47c5e269f944d1ea4ed0cfeb2007c7cd39"
    with pytest.raises(KeyError, match="unknown asset"):
        assets.resolve("nope")


def test_the_build_has_no_network_surface():
    source = (Path(__file__).resolve().parents[2] / "terminologies/icd/icd-11/pipeline/build_bulkimport.py").read_text()
    for marker in ("urllib.request", "urlopen", "requests", "http.client", "OCL_API_TOKEN"):
        assert marker not in source
