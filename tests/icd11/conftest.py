"""Fixtures for the ICD-11 pipeline tests: a small synthetic Simple Tabulation.

The rows exercise the id fallbacks, the sub-code parent rule, the Parent-URI rule (including a
parent that appears *after* its child), a block title with depth markers, the hyperlink cell, and
blank/short editorial lines.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

HEADER = (
    "\ufeffFoundation URI\tLinearization URI\tCode\tBlockId\tTitle\tClassKind\tDepthInKind\tIsResidual\t"
    "ChapterNo\tBrowserLink\tisLeaf\tPrimary tabulation\tGrouping1\tGrouping2\tGrouping3\tGrouping4\t"
    "Grouping5\tCodingNote\tParent\tVersion:2026 Jan 17 - 05:30 UTC"
)


def _link(entity: str) -> str:
    return f'"=hyperlink(""https://icd.who.int/browse/latestrelease/mms/en#{entity}"",""browser"")"'


def _row(entity, code="", block="", title="", kind="category", depth="1", residual="False", chapter="01",
         leaf="False", groupings=(), parent="") -> str:
    g = list(groupings) + [""] * (5 - len(groupings))
    foundation = f"http://id.who.int/icd/entity/{entity}"
    mms = f"http://id.who.int/icd/release/11/mms/{entity}"
    parent_uri = f"http://id.who.int/icd/entity/{parent}" if parent else ""
    cells = [foundation, mms, code, block, f'"{title}"', kind, depth, residual, chapter, _link(entity), leaf, "", *g, "", parent_uri, ""]
    return "\t".join(cells)


ROWS = [
    _row("100", title="Certain infectious or parasitic diseases", kind="chapter"),
    _row("200", block="BlockL1-1A0", title="- Gastroenteritis or colitis of infectious origin", kind="block", parent="100"),
    _row("300", code="1A00", title="- - Cholera", depth="1", groupings=("BlockL1-1A0",), leaf="False"),
    _row("400", code="1A03", title="- - Intestinal infections due to Escherichia coli", groupings=("BlockL1-1A0",)),
    _row("500", code="1A03.0", title="Enteropathogenic Escherichia coli infection", depth="2", leaf="True"),
    # An extension-style row: no Code or BlockId, Parent points at a row defined LATER in the file.
    _row("600", title="Extension child of a later parent", kind="category", chapter="X", parent="700"),
    _row("700", code="XA1B2C", title="Extension stem", chapter="X", groupings=("BlockL1-1A0",)),
    "",
    "Editorial note: this line is not an entity",
]


@pytest.fixture
def tabulation_txt(tmp_path) -> Path:
    path = tmp_path / "SimpleTabulation-ICD-11-MMS-en.txt"
    path.write_text("\r\n".join([HEADER, *ROWS]) + "\r\n", encoding="utf-8")
    return path


@pytest.fixture
def tabulation_zip(tmp_path, tabulation_txt) -> Path:
    path = tmp_path / "SimpleTabulation-ICD-11-MMS-en.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(tabulation_txt, tabulation_txt.name)
        archive.writestr("readme.txt", "synthetic readme")
    return path


@pytest.fixture
def ordered_txt(tmp_path, tabulation_txt) -> Path:
    """The synthetic file minus the deliberately mis-ordered row, so a build can succeed."""
    kept = [line for line in tabulation_txt.read_text(encoding="utf-8").splitlines() if "/entity/600" not in line]
    path = tmp_path / "ordered.txt"
    path.write_text("\r\n".join(kept) + "\r\n", encoding="utf-8")
    return path
