"""Read the DATASUS CID-10 tables and emit ``pt_BR`` name candidates.

The Brazilian CID-10 is a national edition of ICD-10, not a translation of the English
release, and its download is not ClaML. The published tables are semicolon-delimited
ISO-8859-1 (`descrcsv.htm`) and each line ends with a trailing delimiter, which yields an
empty trailing column — the documented schema is therefore read by position, and a header
that does not start with the documented column names is a hard error rather than something
this adapter reshapes.

Codes are emitted with the normalization the source itself requires:

* subcategory ``A000`` (no separator, four characters) becomes ``A00.0``;
* a three-character subcategory row is a category without subcategories and stays ``A09``;
* a group row ``CATINIC``/``CATFIM`` becomes the canonical range id ``A00-A09``;
* a chapter row uses ``NUMCAP`` as a number, because the canonical baseline numbers chapters
  ``1``–``22`` rather than using roman numerals.

The original value is kept on the candidate as ``source_code`` together with the applied rule,
so a reviewer can always see what was transformed. Invalid or blank codes and labels are
skipped with a reason; they are never repaired to force a match. The CID-O morphology tables in
the same archive are counted and ignored: they belong to a different classification.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from ..model import LOCALE_PT_BR, AdapterResult, NameCandidate

AUTHORITY = "DATASUS"
EDITION = "CID-10 (DATASUS V2008 download page; the XML declares V2007)"
ENCODING = "iso-8859-1"
DELIMITER = ";"

# file -> (kind, documented column names)
TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "CID-10-CAPITULOS.CSV": ("chapter", ("NUMCAP", "CATINIC", "CATFIM", "DESCRICAO", "DESCRABREV")),
    "CID-10-GRUPOS.CSV": ("group", ("CATINIC", "CATFIM", "DESCRICAO", "DESCRABREV")),
    "CID-10-CATEGORIAS.CSV": ("category", ("CAT", "CLASSIF", "DESCRICAO", "DESCRABREV", "REFER", "EXCLUIDOS")),
    "CID-10-SUBCATEGORIAS.CSV": (
        "subcategory",
        ("SUBCAT", "CLASSIF", "RESTRSEXO", "CAUSAOBITO", "DESCRICAO", "DESCRABREV", "REFER", "EXCLUIDOS"),
    ),
}
OUT_OF_SCOPE_PREFIX = "CID-O-"
CODE_3 = re.compile(r"^[A-Z]\d{2}$")
GROUP = re.compile(r"^[A-Z]\d{2}-[A-Z]\d{2}$")


def read_tables(source: Path) -> dict[str, list[list[str]]]:
    """Return ``{member name: rows}`` from a ZIP archive or a directory of tables."""
    source = Path(source)
    tables: dict[str, list[list[str]]] = {}
    if source.is_dir():
        for name in sorted(TABLES):
            path = source / name
            if path.is_file():
                tables[name] = _rows(path.read_bytes())
    elif source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = {Path(info.filename).name: info.filename for info in archive.infolist() if not info.is_dir()}
            for name in TABLES:
                if name in members:
                    tables[name] = _rows(archive.read(members[name]))
    else:
        raise ValueError(f"expected a CID10CSV.zip archive or a directory of CSV tables: {source}")
    missing = sorted(set(TABLES) - set(tables))
    if missing:
        raise ValueError(f"{source}: missing required DATASUS tables: {', '.join(missing)}")
    return tables


def _rows(payload: bytes) -> list[list[str]]:
    text = payload.decode(ENCODING)
    return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=DELIMITER)]


def archive_member_names(source: Path) -> list[str]:
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != ".zip":
        return []
    with zipfile.ZipFile(source) as archive:
        return sorted(Path(info.filename).name for info in archive.infolist() if not info.is_dir())


def _column_index(header: list[str], names: tuple[str, ...], source_file: str) -> dict[str, int]:
    found = {name.strip().upper(): position for position, name in enumerate(header) if name.strip()}
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError(
            f"{source_file}: header does not match the documented DATASUS schema; missing column(s): "
            f"{', '.join(missing)} (found: {', '.join(header)})"
        )
    return {name: found[name] for name in names}


def candidates(source: Path, *, locale: str = LOCALE_PT_BR) -> AdapterResult:
    result = AdapterResult(authority=AUTHORITY, locale=locale, edition=EDITION)
    source = Path(source)
    tables = read_tables(source)
    out_of_scope = [name for name in archive_member_names(source) if name.startswith(OUT_OF_SCOPE_PREFIX)]
    result.stats["files"] = {}
    result.stats["out_of_scope_files"] = out_of_scope
    for name, rows in tables.items():
        kind, documented = TABLES[name]
        if not rows:
            raise ValueError(f"{name}: empty table")
        positions = _column_index(rows[0], documented, name)
        emitted = 0
        for row_number, row in enumerate(rows[1:], start=2):
            candidate, reason = _candidate(kind, row, positions, name, row_number, locale)
            if candidate is None:
                result.skip(
                    reason,
                    source_file=name,
                    source_row=row_number,
                    source_code=_raw_code(kind, row, positions),
                )
                continue
            result.candidates.append(candidate)
            emitted += 1
        result.stats["files"][name] = {"rows": len(rows) - 1, "emitted": emitted}
    result.candidates, duplicates = _deduplicate(result.candidates)
    result.stats["duplicate_identical_rows"] = duplicates
    return result


def _deduplicate(candidates: list[NameCandidate]) -> tuple[list[NameCandidate], int]:
    """Drop repeated rows with the same code and label; differing labels are left for alignment."""
    kept: list[NameCandidate] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for candidate in candidates:
        key = (candidate.code, candidate.label)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        kept.append(candidate)
    return kept, duplicates


def _cell(row: list[str], positions: dict[str, int], name: str) -> str:
    position = positions.get(name)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def _raw_code(kind: str, row: list[str], positions: dict[str, int]) -> str:
    if kind == "chapter":
        return _cell(row, positions, "NUMCAP")
    if kind == "group":
        return f"{_cell(row, positions, 'CATINIC')}/{_cell(row, positions, 'CATFIM')}"
    if kind == "category":
        return _cell(row, positions, "CAT")
    return _cell(row, positions, "SUBCAT")


def _candidate(
    kind: str,
    row: list[str],
    positions: dict[str, int],
    source_file: str,
    row_number: int,
    locale: str,
) -> tuple[NameCandidate | None, str]:
    label = _cell(row, positions, "DESCRICAO")
    if not label:
        return None, "blank-label"
    if kind == "chapter":
        raw = _cell(row, positions, "NUMCAP")
        if not raw.isdigit():
            return None, "chapter-number-not-numeric"
        code, source_code = str(int(raw)), raw
    elif kind == "group":
        start, finish = _cell(row, positions, "CATINIC"), _cell(row, positions, "CATFIM")
        code = f"{start}-{finish}"
        source_code = f"{start}/{finish}"
        if not GROUP.match(code):
            return None, "invalid-group-range"
    elif kind == "category":
        source_code = _cell(row, positions, "CAT")
        if not CODE_3.match(source_code):
            return None, "invalid-category-code"
        code = source_code
    else:
        source_code = _cell(row, positions, "SUBCAT")
        letters = source_code.replace(".", "")
        if len(letters) == 4 and CODE_3.match(letters[:3]) and letters[3].isdigit():
            code = f"{letters[:3]}.{letters[3]}"
        elif len(letters) == 3 and CODE_3.match(letters):
            # The published subcategory table also lists categories without subcategories.
            code = letters
        else:
            return None, "invalid-subcategory-code"
    return (
        NameCandidate(
            code=code,
            locale=locale,
            label=label,
            authority=AUTHORITY,
            edition=EDITION,
            kind=kind,
            source_file=source_file,
            source_code=source_code,
            source_row=row_number,
        ),
        "",
    )
