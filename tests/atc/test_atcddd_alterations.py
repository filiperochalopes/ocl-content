"""Tests for the atcddd.fhi.no cumulative alterations HTML reader."""

from __future__ import annotations

from ocl_pipeline_loader import load

atcddd_alterations = load("who/atc", "atcddd_alterations")


def test_parses_rows_with_correct_live_column_order(alterations_path):
    rows = atcddd_alterations.read(alterations_path)
    assert len(rows) == 2
    first = rows[0]
    assert first.old_code == "A01AD02"  # footnote "27)" and &nbsp; stripped
    assert first.substance_name == "benzydamine HCl"
    assert first.new_code == "R02AX03"
    assert first.year_changed == "2018"


def test_skips_the_spacer_row_after_header(alterations_path):
    rows = atcddd_alterations.read(alterations_path)
    codes = [row.old_code for row in rows]
    assert "" not in codes


def test_second_row_has_no_footnote(alterations_path):
    rows = atcddd_alterations.read(alterations_path)
    second = rows[1]
    assert second.old_code == "A03AE02"
    assert second.new_code == "A06AX06"
    assert second.substance_name == "tegaserod"


def test_missing_table_raises():
    import pytest

    with pytest.raises(ValueError):
        atcddd_alterations.parse_html("<html><body>no table here</body></html>")


def test_missing_required_columns_raises():
    import pytest

    html = '<table><tr><th>Only one column</th></tr><tr><td>x</td></tr></table>'
    with pytest.raises(ValueError):
        atcddd_alterations.parse_html(html)


def test_existing_code_suffix_is_stripped():
    html = (
        '<table><tr><th>Previous ATC code</th><th>Substance name</th><th>New ATC code</th></tr>'
        '<tr><td>B02BC10</td><td>fibrinogen, human</td><td>B02BC30 (existing code)</td></tr></table>'
    )
    rows = atcddd_alterations.parse_html(html)
    assert rows[0].new_code == "B02BC30"
