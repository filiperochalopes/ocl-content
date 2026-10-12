"""DATASUS CID-10 table adapter: schema, positional reading, codes, and skip reasons."""

from __future__ import annotations

import pytest

from ocl_pipeline_loader import load
datasus_csv = load("icd/icd-10", "adapters.datasus_csv")
NameCandidate = load("icd/icd-10", "model").NameCandidate


def _by_code(result) -> dict[str, NameCandidate]:
    mapping = {}
    for candidate in result.candidates:
        mapping.setdefault(candidate.code, candidate)
    return mapping


def test_reads_directory_and_normalizes_codes(datasus_dir):
    result = datasus_csv.candidates(datasus_dir)
    codes = {candidate.code for candidate in result.candidates}
    assert {"1", "22", "A00-A09", "A00", "A09", "J09", "U07.1"} <= codes
    assert all(candidate.locale == "pt_BR" for candidate in result.candidates)
    assert all(candidate.authority == "DATASUS" for candidate in result.candidates)


def test_latin1_decoding_preserves_accents(datasus_dir):
    result = datasus_csv.candidates(datasus_dir)
    assert _by_code(result)["A00"].label == "Cólera"
    assert _by_code(result)["A00.0"].label == "Cólera devida a Vibrio cholerae 01, biótipo cholerae"


def test_normalization_records_the_original_token(datasus_dir):
    candidate = _by_code(datasus_csv.candidates(datasus_dir))["A00.0"]
    assert candidate.source_code == "A000"  # four characters without the separator
    assert candidate.source_file == "CID-10-SUBCATEGORIAS.CSV"
    chapter = _by_code(datasus_csv.candidates(datasus_dir))["22"]
    assert chapter.source_code == "22"


def test_category_listed_as_subcategory_is_deduplicated(datasus_dir):
    result = datasus_csv.candidates(datasus_dir)
    a09 = [candidate for candidate in result.candidates if candidate.code == "A09"]
    assert len(a09) == 1
    assert result.stats["duplicate_identical_rows"] == 1


def test_invalid_codes_are_skipped_with_reasons(datasus_dir):
    result = datasus_csv.candidates(datasus_dir)
    reasons = {entry["reason"] for entry in result.skipped}
    assert "invalid-category-code" in reasons
    assert "invalid-subcategory-code" in reasons
    assert all(candidate.code != "12X" for candidate in result.candidates)


def test_zip_input_matches_directory_input_and_reports_cid_o(datasus_dir, datasus_zip):
    from_dir = datasus_csv.candidates(datasus_dir)
    from_zip = datasus_csv.candidates(datasus_zip)
    assert {candidate.code for candidate in from_dir.candidates} == {candidate.code for candidate in from_zip.candidates}
    assert from_zip.stats["out_of_scope_files"] == ["CID-O-CATEGORIAS.CSV"]
    assert all(not candidate.source_file.startswith("CID-O") for candidate in from_zip.candidates)


def test_schema_drift_is_refused(tmp_path):
    directory = tmp_path / "broken"
    directory.mkdir()
    for name, rows in {
        "CID-10-CAPITULOS.CSV": ["NUMCAP;CATINIC;CATFIM;DESCRICAO;DESCRABREV;", "1;A00;B99;Capítulo;I.;"],
        "CID-10-GRUPOS.CSV": ["CATINIC;CATFIM;DESCRICAO;DESCRABREV;", "A00;A09;Grupo;Grupo;"],
        "CID-10-CATEGORIAS.CSV": ["CAT;DESCRICAO;", "A00;Cólera;"],  # documented columns missing
        "CID-10-SUBCATEGORIAS.CSV": ["SUBCAT;DESCRICAO;", "A000;Cólera;"],
    }.items():
        (directory / name).write_text("\n".join(rows) + "\n", encoding="iso-8859-1")
    with pytest.raises(ValueError, match="documented DATASUS schema"):
        datasus_csv.candidates(directory)


def test_missing_table_is_refused(tmp_path):
    directory = tmp_path / "incomplete"
    directory.mkdir()
    (directory / "CID-10-CAPITULOS.CSV").write_text("NUMCAP;CATINIC;CATFIM;DESCRICAO;DESCRABREV;\n", encoding="iso-8859-1")
    with pytest.raises(ValueError, match="missing required DATASUS tables"):
        datasus_csv.candidates(directory)
