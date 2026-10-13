"""Bounded, opt-in cross-check of the TTL hierarchy against atcddd.fhi.no itself.

This is deliberately **not** a full crawl of all ~6,900 ATC codes: a 1st/2nd-level spot-check costs
15 HTTP requests (the index page plus one page per 1st-level chapter); validating every leaf would
need thousands and is out of scope here (see ``README.md``, "Known limits"). What it catches: a
chapter added/removed/renamed, or a 2nd-level group added/removed/renamed, since the pinned BioPortal
submission was published — exactly the gap a stale submission is most likely to have.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

INDEX_URL = "https://atcddd.fhi.no/atc_ddd_index/"
CHAPTER_URL_TEMPLATE = "https://atcddd.fhi.no/atc_ddd_index/?code={code}&showdescription=no"
_CODE_LINE_RE = re.compile(r"^([A-Z]\d{2})\s+(.+)$")
_LAST_UPDATED_RE = re.compile(r"Last updated:\s*([\d-]+)")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "tr"):
            self.chunks.append("\n")

    def text(self) -> str:
        return "".join(self.chunks)


def _page_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()


@dataclass(frozen=True)
class ChapterPage:
    code: str
    title: str
    children: dict[str, str]  # 2nd-level code -> title
    last_updated: str | None


def parse_chapter_page(html: str, code: str) -> ChapterPage:
    text = _page_text(html)
    last_updated_match = _LAST_UPDATED_RE.search(text)
    children: dict[str, str] = {}
    title = ""
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        match = _CODE_LINE_RE.match(line)
        if not match:
            continue
        found_code, label = match.groups()
        if found_code == code:
            title = label
        elif found_code.startswith(code) and len(found_code) == 3:
            children[found_code] = label
    return ChapterPage(code=code, title=title, children=children, last_updated=last_updated_match.group(1) if last_updated_match else None)


def fetch_chapter(code: str, *, opener=urllib.request.urlopen) -> ChapterPage:
    url = CHAPTER_URL_TEMPLATE.format(code=code)
    with opener(url, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_chapter_page(html, code)


@dataclass
class CrosscheckResult:
    chapters_checked: list[str]
    missing_from_atcddd: list[str]  # level-1/2 codes the ontology has but atcddd.fhi.no does not
    missing_from_ontology: list[str]  # level-1/2 codes atcddd.fhi.no has but the ontology does not
    last_updated: str | None


def crosscheck(ontology_codes_by_level: dict[int, set[str]], *, opener=urllib.request.urlopen) -> CrosscheckResult:
    """``ontology_codes_by_level`` maps 1 -> set of chapter codes, 2 -> set of 2nd-level codes."""
    level1 = ontology_codes_by_level.get(1, set())
    level2 = ontology_codes_by_level.get(2, set())
    atcddd_level2: set[str] = set()
    last_updated = None
    checked: list[str] = []
    for chapter_code in sorted(level1):
        page = fetch_chapter(chapter_code, opener=opener)
        checked.append(chapter_code)
        atcddd_level2.update(page.children)
        last_updated = page.last_updated or last_updated
    return CrosscheckResult(
        chapters_checked=checked,
        missing_from_atcddd=sorted(level2 - atcddd_level2),
        missing_from_ontology=sorted(atcddd_level2 - level2),
        last_updated=last_updated,
    )
