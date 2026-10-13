"""Read the WHO ATC/DDD cumulative alterations list published at atcddd.fhi.no.

Stdlib-only HTML table reading (``html.parser``, no BeautifulSoup/pandas dependency — unlike the
sibling ``ciel-scripts`` repository's ``ocl_uploader_whoatc.py``, which this mirrors): the page
publishes exactly one HTML ``<table>``. Its live column order, confirmed 2026-10-12, is
**Previous ATC code, Substance name, New ATC code, Year changed** (header cells carry ``&nbsp;``
inside a double space, e.g. ``Previous  ATC&nbsp;code``), so columns are looked up by normalized
header name rather than by position. A code cell may carry a footnote marker such as
``A01AD02 27)`` (the ``27)`` comes from a ``<sup><a>…</a></sup>`` reference); it is stripped the same
way the script this replaces does. A spacer row with a single empty cell follows the header and is
skipped because it has no code.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ALTERATIONS_URL = "https://atcddd.fhi.no/atc_ddd_alterations__cumulative/atc_alterations/"
_FOOTNOTE_RE = re.compile(r"\s*\d+\)\s*$")
_REQUIRED_COLUMNS = ("Previous ATC code", "New ATC code")


class _FirstTableParser(HTMLParser):
    """Collects the first ``<table>``'s rows as lists of cell text; ignores everything after it."""

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._table_done = False
        self._in_row = False
        self._in_cell = False
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self._table_done:
            return
        if tag == "table" and not self._in_table:
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell = []
        elif tag == "br" and self._in_cell:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if self._table_done:
            return
        if tag in ("td", "th") and self._in_cell:
            self._row.append("".join(self._cell).strip())
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
        elif tag == "table" and self._in_table:
            self._in_table = False
            self._table_done = True

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def _normalize_header(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _clean_code(value: str) -> str:
    value = " ".join((value or "").replace("\xa0", " ").split())
    value = value.replace("(existing code)", "").strip()
    return _FOOTNOTE_RE.sub("", value).strip()


@dataclass(frozen=True)
class Alteration:
    old_code: str
    new_code: str | None
    substance_name: str
    year_changed: str | None
    source_row: int


def parse_html(html: str) -> list[Alteration]:
    parser = _FirstTableParser()
    parser.feed(html)
    if not parser.rows:
        raise ValueError("no <table> found in the alterations page")
    header, *data_rows = parser.rows
    index = {_normalize_header(name): position for position, name in enumerate(header)}
    missing = [name for name in _REQUIRED_COLUMNS if name not in index]
    if missing:
        raise ValueError(f"alterations table is missing columns {missing}; header was {header!r}")
    substance_position = index.get("Substance name")
    year_position = index.get("Year changed")

    def cell(row: list[str], position: int | None) -> str:
        return row[position].strip() if position is not None and position < len(row) else ""

    alterations: list[Alteration] = []
    for row_number, row in enumerate(data_rows, start=2):
        old_code = _clean_code(cell(row, index["Previous ATC code"]))
        if not old_code:
            continue  # the decorative spacer row right after the header, or a blank line
        new_code = _clean_code(cell(row, index["New ATC code"])) or None
        alterations.append(
            Alteration(
                old_code=old_code,
                new_code=new_code,
                substance_name=cell(row, substance_position),
                year_changed=cell(row, year_position) or None,
                source_row=row_number,
            )
        )
    return alterations


def fetch(url: str = ALTERATIONS_URL, *, opener=urllib.request.urlopen) -> bytes:
    with opener(url, timeout=60) as response:
        return response.read()


def read(path: Path) -> list[Alteration]:
    payload = Path(path).read_bytes()
    return parse_html(payload.decode("utf-8", errors="replace"))
