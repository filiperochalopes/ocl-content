"""Reading the Simple Tabulation: ids, parents, classes, release, and skipped rows."""

from __future__ import annotations

import pytest

from ocl_pipeline_loader import load
st = load("icd/icd-11", "simple_tabulation")


def by_id(tabulation):
    return {row.id: row for row in tabulation.rows}


def test_release_comes_from_the_version_header(tabulation_zip):
    tabulation = st.read(tabulation_zip)
    assert tabulation.release == "2026-01"
    assert tabulation.version_label == "Version:2026 Jan 17 - 05:30 UTC"


def test_zip_and_txt_give_the_same_rows(tabulation_zip, tabulation_txt):
    assert st.read(tabulation_zip).rows == st.read(tabulation_txt).rows


def test_id_fallback_order(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert "Chapter-01" in rows            # chapter without Code/BlockId
    assert "BlockL1-1A0" in rows           # BlockId
    assert "1A00" in rows                  # Code
    assert "600" in rows                   # suffix after /mms/


def test_blank_and_editorial_lines_are_skipped_and_counted(tabulation_txt):
    tabulation = st.read(tabulation_txt)
    assert [entry["reason"] for entry in tabulation.skipped] == ["no-supported-identifier"] * 2
    assert len(tabulation.rows) == 7


def test_titles_lose_depth_markers_and_keep_everything_else(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert rows["BlockL1-1A0"].title == "Gastroenteritis or colitis of infectious origin"
    assert rows["1A00"].title == "Cholera"
    assert rows["1A03"].title == "Intestinal infections due to Escherichia coli"


def test_classes(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert rows["Chapter-01"].concept_class == "Chapter"
    assert rows["BlockL1-1A0"].concept_class == "Block"
    assert rows["1A00"].concept_class == "Diagnosis"


def test_parents(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert rows["Chapter-01"].parent is None
    assert rows["BlockL1-1A0"].parent == "Chapter-01"   # via the Parent foundation URI
    assert rows["1A00"].parent == "BlockL1-1A0"          # deepest grouping
    assert rows["1A03.0"].parent == "1A03"               # sub-code under its stem


def test_a_parent_defined_later_in_the_file_is_still_resolved(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert rows["600"].parent == "XA1B2C"


def test_browser_link_is_pinned_to_the_release(tabulation_txt):
    rows = by_id(st.read(tabulation_txt))
    assert rows["1A00"].browser_link == "https://icd.who.int/browse/2026-01/mms/en#300"


def test_a_file_without_a_version_cell_is_refused(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("Foundation URI\tCode\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Version"):
        st.read(path)


def test_missing_input_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        st.read(tmp_path / "nope.zip")
