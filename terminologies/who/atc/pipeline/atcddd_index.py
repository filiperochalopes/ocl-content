"""Reproducible, read-only crawl of the public WHOCC ATC/DDD Index.

The index exposes hierarchy nodes through ``?code=<ATC>&showdescription=no``.
This crawler fetches the root and every non-leaf node (levels 1--4), extracts
levels 1--4 from hierarchy links, and extracts level-5 codes from the level-4
page's authoritative ATC table. It therefore collects all five ATC levels
without making a request for every individual level-5 code.

It is comparison evidence only. It does not create, update, retire, or map OCL
content.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Protocol

INDEX_URL = "https://atcddd.fhi.no/atc_ddd_index/"
PAGE_URL_TEMPLATE = INDEX_URL + "?code={code}&showdescription=no"
DEFAULT_USER_AGENT = "ocl-content-who-atc-index-crawler/1.0 (read-only comparison)"
CODE_RE = re.compile(r"^(?:[A-Z]|[A-Z]\d{2}|[A-Z]\d{2}[A-Z]|[A-Z]\d{2}[A-Z]{2}|[A-Z]\d{2}[A-Z]{2}\d{2})$")
LAST_UPDATED_RE = re.compile(r"Last updated:\s*([0-9-]+)")
_LEVEL_BY_LENGTH = {1: 1, 3: 2, 4: 3, 5: 4, 7: 5}


class _ReadableResponse(Protocol):
    def read(self) -> bytes: ...

    def __enter__(self) -> "_ReadableResponse": ...

    def __exit__(self, exc_type, exc, traceback) -> None: ...


@dataclass(frozen=True)
class IndexRecord:
    code: str
    title: str
    level: int
    parent: str | None


@dataclass
class CrawlResult:
    records: list[IndexRecord]
    pages_requested: int
    errors: list[str]
    last_updated: str | None

    @property
    def counts_by_level(self) -> dict[int, int]:
        return {level: sum(record.level == level for record in self.records) for level in range(1, 6)}


@dataclass(frozen=True)
class AuditRow:
    code: str
    level: int
    status: str
    bioportal_name: str | None
    who_name: str | None


@dataclass(frozen=True)
class Comparison:
    rows: list[AuditRow]
    bioportal_by_level: dict[int, int]
    who_by_level: dict[int, int]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "bioportal_only": sum(row.status == "bioportal_only" for row in self.rows),
            "who_only": sum(row.status == "who_only" for row in self.rows),
            "label_differences": sum(row.status == "label_difference" for row in self.rows),
        }


class _IndexPageParser(HTMLParser):
    """Collect hierarchy links and every HTML-table row from one index page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            self._anchor_href = attributes.get("href")
            self._anchor_text = []
        elif tag == "table" and not self._in_table:
            self._in_table = True
            self._table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell = []
        elif tag == "br":
            if self._in_cell:
                self._cell.append(" ")
            if self._anchor_href is not None:
                self._anchor_text.append(" ")
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_href is not None:
            self.links.append((self._anchor_href, _normalise_whitespace("".join(self._anchor_text))))
            self._anchor_href = None
            self._anchor_text = []
        elif tag in ("td", "th") and self._in_cell:
            self._row.append(_normalise_whitespace("".join(self._cell)))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._row:
                self._table.append(self._row)
            self._in_row = False
        elif tag == "table" and self._in_table:
            self.tables.append(self._table)
            self._table = []
            self._in_table = False
        elif tag in ("p", "div", "li", "tr"):
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_text.append(data)
        if self._in_cell:
            self._cell.append(data)
        self.text.append(data)


def _normalise_whitespace(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def label_key(value: str) -> str:
    """Whitespace/case-normalised comparison key; punctuation remains meaningful."""
    return _normalise_whitespace(value).casefold()


def code_level(code: str) -> int:
    if not CODE_RE.fullmatch(code):
        raise ValueError(f"invalid ATC code: {code!r}")
    try:
        return _LEVEL_BY_LENGTH[len(code)]
    except KeyError as error:
        raise ValueError(f"invalid ATC code length: {code!r}") from error


def code_from_url(url: object) -> str | None:
    """Read the ``code`` query parameter from a string or urllib Request."""
    full_url = url.full_url if isinstance(url, urllib.request.Request) else str(url)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(full_url).query)
    values = query.get("code")
    return values[0] if values else None


def page_url(code: str) -> str:
    code_level(code)
    return PAGE_URL_TEMPLATE.format(code=urllib.parse.quote(code, safe=""))


def _parse(html: str) -> _IndexPageParser:
    parser = _IndexPageParser()
    parser.feed(html)
    parser.close()
    return parser


def _index_links(parser: _IndexPageParser) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for href, title in parser.links:
        parsed = urllib.parse.urlparse(href)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("showdescription") != ["no"]:
            continue
        code = query.get("code", [None])[0]
        if code is None or not title:
            continue
        code_level(code)
        result.append((code, title))
    return result


def parse_nonleaf_children(html: str, parent_code: str | None) -> list[tuple[str, str]]:
    """Return only direct hierarchy children; reject unexpected descendant links."""
    parent_level = 0 if parent_code is None else code_level(parent_code)
    expected_level = parent_level + 1
    if expected_level > 4:
        raise ValueError("level-5 records are read from authoritative table rows, not hierarchy links")

    children: dict[str, str] = {}
    for code, title in _index_links(_parse(html)):
        level = code_level(code)
        if parent_code is None:
            if level != 1:
                raise ValueError(f"unexpected non-chapter hierarchy link on index page: {code}")
        else:
            if code == parent_code or not code.startswith(parent_code):
                continue  # breadcrumb or navigation link outside this branch
            if level != expected_level:
                raise ValueError(f"unexpected non-direct descendant link for {parent_code}: {code}")
        old = children.setdefault(code, title)
        if old != title:
            raise ValueError(f"conflicting hierarchy labels for {code}: {old!r} versus {title!r}")
    return sorted(children.items())


def parse_leaf_rows(html: str, parent_code: str) -> list[tuple[str, str]]:
    """Read direct level-5 children from the level-4 page's ATC table."""
    if code_level(parent_code) != 4:
        raise ValueError(f"leaf rows may only be read from a level-4 page, got {parent_code!r}")
    leaves: dict[str, str] = {}
    for table in _parse(html).tables:
        for row in table:
            if len(row) < 2:
                continue
            code = re.sub(r"\s*\d+\)\s*$", "", row[0]).strip()
            if not CODE_RE.fullmatch(code):
                continue
            if code == parent_code:
                continue  # some level-4 pages repeat their own heading as a table row
            if code_level(code) != 5 or not code.startswith(parent_code):
                raise ValueError(f"unexpected ATC table code on {parent_code} page: {code}")
            title = _normalise_whitespace(row[1])
            if not title:
                raise ValueError(f"ATC table row has no label: {code}")
            old = leaves.setdefault(code, title)
            if old != title:
                raise ValueError(f"conflicting table labels for {code}: {old!r} versus {title!r}")
    return sorted(leaves.items())


def _fetch(
    url: str,
    *,
    opener: Callable[..., _ReadableResponse],
    timeout: float,
    user_agent: str,
) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with opener(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def crawl(
    *,
    opener: Callable[..., _ReadableResponse] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
    delay_seconds: float = 0.05,
    timeout: float = 30,
    workers: int = 1,
    user_agent: str = DEFAULT_USER_AGENT,
) -> CrawlResult:
    """Crawl all ATC hierarchy levels from the public WHOCC index.

    A root request discovers level 1. Requests for levels 1--3 discover the
    next hierarchy level. Each level-4 request reads direct level-5 children
    from its ATC table. Requests within a hierarchy level may run in a bounded
    worker pool; hierarchy processing and output order stay deterministic. Any
    failed request aborts the crawl rather than producing a partial comparison
    masquerading as a complete one.
    """
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    records: dict[str, IndexRecord] = {}
    pages_requested = 0
    last_updated: str | None = None

    def fetch_batch(urls: list[str]) -> list[str]:
        nonlocal pages_requested, last_updated
        if not urls:
            return []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for position, url in enumerate(urls):
                if pages_requested or position:
                    sleeper(delay_seconds)
                futures.append(pool.submit(_fetch, url, opener=opener, timeout=timeout, user_agent=user_agent))
                pages_requested += 1
            pages = [future.result() for future in futures]
        for html in pages:
            match = LAST_UPDATED_RE.search(_normalise_whitespace("".join(_parse(html).text)))
            last_updated = match.group(1) if match else last_updated
        return pages

    def add(code: str, title: str, parent: str | None) -> None:
        record = IndexRecord(code=code, title=title, level=code_level(code), parent=parent)
        previous = records.get(code)
        if previous is not None and previous != record:
            raise ValueError(f"conflicting record for {code}: {previous!r} versus {record!r}")
        records[code] = record

    root_html = fetch_batch([INDEX_URL])[0]
    frontier: list[tuple[str, str, str | None]] = [
        (code, title, None) for code, title in parse_nonleaf_children(root_html, parent_code=None)
    ]
    while frontier:
        current = sorted(frontier, key=lambda item: item[0])
        frontier = []
        for code, title, parent in current:
            add(code, title, parent)
        pages = fetch_batch([page_url(code) for code, _, _ in current])
        for (code, _, _), html in zip(current, pages, strict=True):
            level = code_level(code)
            if level == 4:
                for leaf_code, leaf_title in parse_leaf_rows(html, code):
                    add(leaf_code, leaf_title, code)
            else:
                for child_code, child_title in parse_nonleaf_children(html, parent_code=code):
                    frontier.append((child_code, child_title, code))

    ordered = sorted(records.values(), key=lambda record: (record.level, record.code))
    return CrawlResult(records=ordered, pages_requested=pages_requested, errors=[], last_updated=last_updated)


def compare(ontology, crawl_result: CrawlResult) -> Comparison:
    """Compare exact code membership and normalised preferred labels at all levels."""
    bioportal = {entry.code: entry for entry in ontology.classes}
    who = {record.code: record for record in crawl_result.records}
    rows: list[AuditRow] = []
    for code in sorted(set(bioportal) | set(who)):
        bioportal_entry = bioportal.get(code)
        who_record = who.get(code)
        if bioportal_entry is None:
            assert who_record is not None
            rows.append(AuditRow(code, who_record.level, "who_only", None, who_record.title))
        elif who_record is None:
            rows.append(AuditRow(code, bioportal_entry.level, "bioportal_only", bioportal_entry.title, None))
        elif label_key(bioportal_entry.title) != label_key(who_record.title):
            rows.append(AuditRow(code, who_record.level, "label_difference", bioportal_entry.title, who_record.title))
    return Comparison(
        rows=rows,
        bioportal_by_level={level: sum(entry.level == level for entry in bioportal.values()) for level in range(1, 6)},
        who_by_level=crawl_result.counts_by_level,
    )


def report_payload(*, crawl_result: CrawlResult, comparison: Comparison, bioportal_path: Path, bioportal_sha256: str, bioportal_version: str) -> dict:
    """Return serialisable evidence for the local meeting audit."""
    return {
        "metadata": {
            "who_source": INDEX_URL,
            "crawl_scope": "all ATC levels 1-5; hierarchy links for levels 1-4 and authoritative table rows for level 5",
            "pages_requested": crawl_result.pages_requested,
            "request_errors": crawl_result.errors,
            "who_last_updated": crawl_result.last_updated,
            "bioportal_file": str(bioportal_path),
            "bioportal_sha256": bioportal_sha256,
            "bioportal_version": bioportal_version,
            "comparison_note": "Differences are review candidates; no semantic equivalence, retirement, or mapping is inferred.",
            "label_comparison": "case- and whitespace-normalised; punctuation remains meaningful",
        },
        "counts": {
            "bioportal_total": sum(comparison.bioportal_by_level.values()),
            "who_total": sum(comparison.who_by_level.values()),
            "bioportal_by_level": comparison.bioportal_by_level,
            "who_by_level": comparison.who_by_level,
            **comparison.counts,
        },
        "records": [asdict(row) for row in comparison.rows],
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_html(path: Path, payload: dict) -> None:
    """Write a standalone searchable audit view without external dependencies."""
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    counts = payload["counts"]
    metadata = payload["metadata"]
    body = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>WHOCC ATC/DDD Index vs BioPortal ATC audit</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#17202a}} h1{{margin-bottom:.2rem}} .meta{{color:#53606d}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}} .card{{border:1px solid #ccd5df;border-radius:8px;padding:12px;min-width:150px}} .n{{font-size:1.5rem;font-weight:700}}
.controls{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}} input,select,button{{padding:8px;border:1px solid #aab7c4;border-radius:5px;background:#fff}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}} th,td{{border-bottom:1px solid #dde4eb;padding:8px;text-align:left;vertical-align:top}} th{{position:sticky;top:0;background:#f7f9fb}} .who_only{{background:#eaf7ec}} .bioportal_only{{background:#fff0ee}} .label_difference{{background:#fff8df}} code{{font-size:.9em}}
</style></head><body>
<h1>WHOCC ATC/DDD Index vs BioPortal ATC</h1>
<p class=\"meta\">WHO source: <code>{escape(metadata['who_source'])}</code> · WHO page last updated: <b>{escape(str(metadata['who_last_updated']))}</b> · all levels 1–5 · {metadata['pages_requested']:,} requests</p>
<p class=\"meta\">BioPortal snapshot: <code>{escape(metadata['bioportal_file'])}</code> · version <b>{escape(metadata['bioportal_version'])}</b> · SHA-256 <code>{escape(metadata['bioportal_sha256'])}</code></p>
<div class=\"cards\"><div class=\"card\"><div class=\"n\">{counts['who_total']:,}</div>WHO total</div><div class=\"card\"><div class=\"n\">{counts['bioportal_total']:,}</div>BioPortal total</div><div class=\"card\"><div class=\"n\">{counts['who_only']:,}</div>WHO only</div><div class=\"card\"><div class=\"n\">{counts['bioportal_only']:,}</div>BioPortal only</div><div class=\"card\"><div class=\"n\">{counts['label_differences']:,}</div>Label differences</div></div>
<p><b>Interpretation:</b> exact-code and preferred-label comparison only. A row is a review candidate, not a lifecycle, equivalence, or mapping decision. Label comparison is case/whitespace normalised; punctuation remains meaningful.</p>
<div class=\"controls\"><input id=\"query\" placeholder=\"Filter code or name\"><select id=\"level\"><option value=\"\">All levels</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select><select id=\"status\"><option value=\"\">All differences</option><option value=\"who_only\">WHO only</option><option value=\"bioportal_only\">BioPortal only</option><option value=\"label_difference\">Label difference</option></select><button id=\"csv\">Export filtered CSV</button><span id=\"shown\"></span></div>
<table><thead><tr><th>Code</th><th>Level</th><th>Difference</th><th>BioPortal label</th><th>WHO label</th></tr></thead><tbody id=\"rows\"></tbody></table>
<script>const audit={data}; const rows=audit.records; const el=id=>document.getElementById(id); function selected(){{const q=el('query').value.toLowerCase(),l=el('level').value,s=el('status').value; return rows.filter(r=>(!q||[r.code,r.bioportal_name,r.who_name].filter(Boolean).join(' ').toLowerCase().includes(q))&&(!l||String(r.level)===l)&&(!s||r.status===s));}} function render(){{const shown=selected();el('rows').innerHTML=shown.map(r=>`<tr class="${{r.status}}"><td><code>${{r.code}}</code></td><td>${{r.level}}</td><td>${{r.status.replace('_',' ')}}</td><td>${{r.bioportal_name??''}}</td><td>${{r.who_name??''}}</td></tr>`).join('');el('shown').textContent=`${{shown.length.toLocaleString()}} rows`;}} for(const id of ['query','level','status']) el(id).addEventListener(id==='query'?'input':'change',render); el('csv').addEventListener('click',()=>{{const header=['code','level','status','bioportal_name','who_name'];const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv=[header.join(','),...selected().map(r=>header.map(k=>quote(r[k])).join(','))].join('\\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='whoatc_index_vs_bioportal_filtered.csv';a.click();URL.revokeObjectURL(a.href);}}); render();</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
