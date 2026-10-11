"""tools/ocl_artifacts.py: parts are capped by their COMPRESSED size, and each one is an upload ZIP."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

import ocl_artifacts as subject


def line(i: int, filler: str) -> dict:
    return {"type": "Concept", "id": f"C{i:05d}", "names": [{"name": filler, "locale": "en"}]}


def compressible(n: int) -> list[dict]:
    return [line(i, "Cholera due to Vibrio cholerae 01, biovar cholerae " * 3) for i in range(n)]


def incompressible(n: int) -> list[dict]:
    return [line(i, hashlib.sha256(str(i).encode()).hexdigest() * 6) for i in range(n)]


def test_the_cap_is_on_compressed_size_not_raw_size(tmp_path):
    lines = compressible(2000)
    raw = sum(len(subject.serialize(item)) for item in lines)
    cap = 20_000
    parts = subject.write_parts(tmp_path, lines, cap)
    assert raw > 20 * cap                                       # a raw cap would need dozens of parts
    assert len(parts) <= 3                                      # compressed, a couple are enough
    assert all(part.zip_bytes <= cap for part in parts)
    assert all((tmp_path / part.zip).stat().st_size == part.zip_bytes for part in parts)
    assert max(part.bytes for part in parts) > cap              # a part's NDJSON may be far larger than the cap


def test_every_part_is_a_zip_holding_exactly_its_ndjson(tmp_path):
    parts = subject.write_parts(tmp_path, incompressible(300), 6_000)
    assert len(parts) > 1
    for part in parts:
        with zipfile.ZipFile(tmp_path / part.zip) as archive:
            assert archive.namelist() == [part.name]
            assert archive.read(part.name) == (tmp_path / part.name).read_bytes()
        assert part.sha256 == hashlib.sha256((tmp_path / part.name).read_bytes()).hexdigest()
        assert part.zip_sha256 == hashlib.sha256((tmp_path / part.zip).read_bytes()).hexdigest()


def test_the_ndjson_parts_concatenate_to_the_bundle_in_order(tmp_path):
    lines = incompressible(800)
    parts = subject.write_parts(tmp_path, lines, 30_000)
    bundle = subject.write_bundle(tmp_path, lines)
    assert len(parts) > 1
    assert b"".join((tmp_path / p.name).read_bytes() for p in parts) == (tmp_path / bundle.name).read_bytes()
    assert [p.name for p in parts] == [f"bulkimport_part_{n:03d}.ndjson" for n in range(1, len(parts) + 1)]
    assert [p.zip for p in parts] == [f"bulkimport_part_{n:03d}.zip" for n in range(1, len(parts) + 1)]
    assert sum(p.lines for p in parts) == len(lines)


@pytest.mark.parametrize("cap", [3_000, 12_000, 50_000, 200_000])
def test_the_cap_holds_for_data_that_barely_compresses(tmp_path, cap):
    parts = subject.write_parts(tmp_path, incompressible(1500), cap)
    assert all(part.zip_bytes <= cap for part in parts)
    # and parts are not absurdly small: every part but the last is at least half full
    assert all(part.zip_bytes >= cap // 2 for part in parts[:-1])


def test_parts_are_deterministic_byte_for_byte(tmp_path):
    first = subject.write_parts(tmp_path / "a", incompressible(500), 20_000)
    second = subject.write_parts(tmp_path / "b", incompressible(500), 20_000)
    assert [p.zip_sha256 for p in first] == [p.zip_sha256 for p in second]


def test_a_resource_that_alone_exceeds_the_compressed_cap_is_refused(tmp_path):
    with pytest.raises(ValueError, match="cannot be split across parts"):
        subject.write_parts(tmp_path, [line(1, hashlib.sha256(b"x").hexdigest() * 200)], 300)


def test_a_rerun_removes_stale_ndjson_and_zip_parts(tmp_path):
    assert len(subject.write_parts(tmp_path, incompressible(600), 20_000)) > 1
    parts = subject.write_parts(tmp_path, compressible(5), 10 ** 6)
    assert len(parts) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bulkimport_part_001.ndjson", "bulkimport_part_001.zip"]


def test_part_info_from_disk_matches_what_was_written(tmp_path):
    parts = subject.write_parts(tmp_path, compressible(50), 10 ** 6)
    assert subject.part_info_from_disk(tmp_path / parts[0].name) == parts[0]
    (tmp_path / parts[0].zip).unlink()
    bare = subject.part_info_from_disk(tmp_path / parts[0].name)
    assert bare.zip == "" and bare.lines == parts[0].lines


def test_the_manifest_lists_the_upload_zips_in_order(tmp_path):
    parts = subject.write_parts(tmp_path, incompressible(400), 15_000)
    bundle = subject.write_bundle(tmp_path, incompressible(400))
    manifest = subject.build_manifest(target={}, mode="m", upload_ready=False, parts=[p.__dict__ for p in parts],
                                      bundle=bundle.__dict__, method="deflate",
                                      bundle_archive="x.bundle.zip", parts_archive="x.parts.zip")
    assert manifest["upload"]["order"] == [p.zip for p in parts]
    assert ".bundle.zip" in manifest["upload"]["note"] and ".parts.zip" in manifest["upload"]["note"]
    assert manifest["upload"]["bundle_archive"] == "x.bundle.zip"
    assert manifest["upload"]["parts_archive"] == "x.parts.zip"
    assert manifest["upload"]["mechanism"] == "manual"


def test_zip_payload_is_a_plain_deflate_zip_any_importer_can_read():
    data = subject.zip_payload("x.ndjson", b'{"a":1}\n')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("x.ndjson")
        assert info.compress_type == zipfile.ZIP_DEFLATED and info.date_time == subject.ZIP_DATE
