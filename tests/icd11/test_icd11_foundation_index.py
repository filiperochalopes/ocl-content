"""Tests for the stdlib reader of the ICD-API search index and the flat Foundation-alias CSV reader.

The index fixture is a hand-encoded protobuf with exactly the fields the reader consumes (see the
module docstring of ``foundation_index.py``), so the tests exercise the real wire format without
shipping WHO's index file.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ocl_pipeline_loader import load

fi = load("who/icd-11", "foundation_index")
flat = load("who/icd-11", "flat_synonyms")

RELEASE = "2026-01"
BASE = f"http://id.who.int/icd/release/11/{RELEASE}/mms"
COMPOSITE_A = f"{BASE}/1 & {BASE}/2"
COMPOSITE_B = f"{BASE}/3 / {BASE}/4"


def varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        out.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(out)


def field(number: int, value) -> bytes:
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return varint((number << 3) | 2) + varint(len(value)) + value


def shared_info(label: str, foundation_id: int) -> bytes:
    return field(10, label) + field(11, foundation_id)


def index_record(shared_no: int, title_no: int, uri: str) -> bytes:
    record = field(5, field(10, shared_no))
    if title_no:  # protobuf omits a zero value, exactly as the real index does
        record += field(9, title_no)
    if uri:
        record += field(100, field(6, uri))
    return record


def build_index(shared: list[tuple[str, int]], records: list[bytes], section: str = f"{RELEASE}_MMS") -> bytes:
    data = b"".join(field(10, shared_info(label, fid)) for label, fid in shared)
    data += field(90, b"".join(field(2, record) for record in records))
    data += field(93, field(1, section))  # section number 0 is omitted by protobuf
    return data


SHARED = [
    ("Cholera due to Vibrio cholerae O1", 555),   # 0: entity title
    ("cholera O1", 0),                             # 1: synonym of 0
    ("Cholera classical", 0),                      # 2: synonym of 0
    ("Obesity with cholera", 666),                 # 3: title of the second entity
]


def good_index() -> bytes:
    return build_index(
        SHARED,
        [
            index_record(0, 0, COMPOSITE_A),   # position 0: title record of the first entity
            index_record(1, 0, COMPOSITE_A),   # synonym (TitleIndexInfoNo -> 0)
            index_record(2, 0, COMPOSITE_A),   # synonym
            index_record(3, 3, COMPOSITE_A),   # position 3: a SECOND entity attached to the same composite
            index_record(0, 4, ""),            # position 4: a flat record, not a composite: ignored
            index_record(3, 5, COMPOSITE_B),   # position 5: title record of another composite
        ],
    )


# --- foundation_index ---------------------------------------------------------------------------


def test_decode_returns_title_and_synonyms_for_each_composite():
    entities = fi.decode_index_entities(good_index(), RELEASE)
    first = entities[COMPOSITE_A][0]
    assert first.foundation_id == "555"
    assert first.title == "Cholera due to Vibrio cholerae O1"
    assert first.synonyms == ("cholera O1", "Cholera classical")


def test_one_composite_can_carry_several_entities_in_index_order():
    entities = fi.decode_index_entities(good_index(), RELEASE)
    assert [entity.title for entity in entities[COMPOSITE_A]] == [
        "Cholera due to Vibrio cholerae O1", "Obesity with cholera",
    ]
    assert entities[COMPOSITE_A][1].foundation_id == "666"


def test_a_record_without_a_composite_uri_is_ignored():
    entities = fi.decode_index_entities(good_index(), RELEASE)
    assert set(entities) == {COMPOSITE_A, COMPOSITE_B}


def test_a_missing_release_section_is_an_error_not_an_empty_result():
    with pytest.raises(ValueError, match="no 2025-01_MMS section"):
        fi.decode_index_entities(good_index(), "2025-01")


def test_a_truncated_index_is_reported_as_a_value_error():
    with pytest.raises(ValueError):
        fi.decode_index_entities(good_index()[:-3], RELEASE)


def test_entity_names_lists_titles_then_synonyms_without_duplicates():
    entities = fi.decode_index_entities(good_index(), RELEASE)
    assert fi.entity_names(entities[COMPOSITE_A]) == (
        "Cholera due to Vibrio cholerae O1", "cholera O1", "Cholera classical", "Obesity with cholera",
    )


# --- flat_synonyms --------------------------------------------------------------------------------

FLAT_FIELDS = [
    "code", "code_kind", "code_title", "code_foundation_id", "code_browser_link", "foundation_id",
    "foundation_title", "foundation_browser_link", "evidence", "foundation_relation", "entities_in_code",
]


def flat_row(code, title, foundation_id, evidence="narrower", code_title="Cholera", relation="direct_child"):
    return {
        "code": code, "code_kind": "stem", "code_title": code_title, "code_foundation_id": "1",
        "code_browser_link": "", "foundation_id": foundation_id, "foundation_title": title,
        "foundation_browser_link": "", "evidence": evidence, "foundation_relation": relation, "entities_in_code": "2",
    }


def write_flat(path: Path, rows) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FLAT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_flat_reader_groups_names_by_code_in_file_order(tmp_path):
    path = write_flat(tmp_path / "flat.csv", [
        flat_row("1A00", "Enteritis due to cholera", "10"),
        flat_row("1A03", "E. coli enteritis", "11"),
        flat_row("1A00", "Cholera, non-O1", "12", evidence="residual_rollup"),
    ])
    result = flat.read(path)
    assert [alias.name for alias in result.by_code["1A00"]] == ["Enteritis due to cholera", "Cholera, non-O1"]
    assert result.by_code["1A00"][1].evidence == "residual_rollup"
    assert result.by_code["1A00"][1].foundation_id == "12"
    assert result.total_read == 3
    assert result.evidence_counts == {"narrower": 2, "residual_rollup": 1}


def test_flat_reader_drops_a_repeated_name_within_a_code_case_insensitively(tmp_path):
    path = write_flat(tmp_path / "flat.csv", [
        flat_row("1A00", "Cholera, non-O1", "10"),
        flat_row("1A00", "cholera, NON-O1", "11"),
    ])
    result = flat.read(path)
    assert [alias.name for alias in result.by_code["1A00"]] == ["Cholera, non-O1"]
    assert result.duplicate_names == 1


def test_flat_reader_rejects_a_csv_without_the_required_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("code,title\n1A00,Cholera\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        flat.read(path)


def test_flat_reader_skips_rows_without_a_code_or_a_name_and_reports_them(tmp_path):
    path = write_flat(tmp_path / "flat.csv", [flat_row("", "No code", "10"), flat_row("1A00", "", "11")])
    result = flat.read(path)
    assert result.by_code == {}
    assert result.skipped == 2
