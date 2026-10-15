"""Standalone HTML review of the indexed post-coordinated codes.

Not a build step: nothing here is imported by ``build_bulkimport.py``, and the HTML is never part
of a bulk-import bundle. It exists so the owner can review, before any ``--include-rejected``
decision, how each composite is built from WHO's three post-coordination concepts:

- **Stem code**: the root code — generally a diagnosis. Every composite has a first stem;
  ``code`` 's "stem code(s)" is 2 only when a *second* stem is also present (a ``/`` component),
  which is a different thing from an extension value.
- **Extension code**: a value after a stem's ``&`` — laterality, severity, causing agent, and so on;
  a composite can carry none, one, or several. Counted from the code string itself
  (``PostcoordRow.extension_count``/``has_extension_code``), never from the hydrated
  ``extension_codes``/``axes`` columns: those come from one ``/describe`` call and do not reliably
  decompose every composite (confirmed: a composite with its own registered Foundation entity can
  hydrate to an empty ``extension_codes`` despite a real ``&`` in its code, and a second-stem-only
  composite, no ``&`` at all, can hydrate to a non-empty one because ``/describe`` reported the second
  stem itself as an axis value).
- **Foundation code**: WHO's own registered entity for a term. Most are a single stem or extension's
  own entity, but some *post-coordinated expressions themselves* have been given their own Foundation
  entity too — that is exactly what ``foundation_entity_id`` being set means on a composite row: this
  whole expression (not just its parts) is registered as a WHO Foundation code, not merely a computed
  combination. A Foundation code's own browser page (``.../foundation/en#<id>``) proves that
  registration and carries its own title/definition/synonyms — but it does **not** display the
  expression combined with its stem the way the MMS link does (confirmed directly: opening the
  Foundation page for an extension's own entity shows only that entity, never the stem + extension
  together). The **MMS link** is the one that shows the combination: it opens the *first stem's* MMS
  page with the Postcoordination panel pre-selecting the exact extension/second-stem values, which
  works for every composite with resolvable ids, Foundation code or not.
"""

from __future__ import annotations

import html
from pathlib import Path

from .postcoordinated import PostcoordRow

# Deliberately dense: small font, minimal padding, no row wrapping — built to let several thousand
# rows fit on screen at once and be scanned/filtered quickly, not to be printed.
STYLE = """
 body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 16px; color: #1b1b1b; font-size: 12px; }
 h1 { font-size: 15px; margin: 0 0 6px; }
 .meta { color: #555; font-size: 11px; margin-bottom: 8px; line-height: 1.45; }
 .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }
 .toolbar label { font-size: 11px; color: #333; display: flex; flex-direction: column; gap: 2px; }
 .toolbar select, .toolbar input[type=text] { font-size: 12px; padding: 3px 5px; }
 .toolbar input[type=text] { width: 300px; }
 #count { font-size: 13px; font-weight: 700; margin-left: auto; white-space: nowrap; background: #eef4ff; padding: 4px 10px; border-radius: 4px; }
 table { border-collapse: collapse; width: 100%; font-size: 11px; table-layout: fixed; }
 th, td { border: 1px solid #ddd; padding: 1px 5px; vertical-align: top; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
 th { background: #f4f4f4; position: sticky; top: 0; text-align: left; }
 tr:nth-child(even) { background: #fafafa; }
 tr.rejected { background: #fff0f0; }
 tr.rejected:nth-child(even) { background: #ffe6e6; }
 td.code, td.entity { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
 td.title, th.title { white-space: normal; }
 .own { color: #0a7a2a; font-weight: 600; }
 .composed { color: #8a6d00; }
 .count { font-weight: 600; }
 a { color: #0b57d0; text-decoration: none; }
 .dash { color: #aaa; }
"""

# (key, label, css-class, width%)
COLUMNS = [
    ("code", "Code", "code", 11),
    ("title", "Title", "title", 23),
    ("title_source", "Title source", "", 11),
    ("describe_status", "Describe", "", 7),
    ("stems", "Stem code(s)", "", 6),
    ("ext", "Extension code(s)", "", 6),
    ("entity_id", "Composite URI", "entity", 12),
    ("foundation", "Foundation code", "", 9),
    ("mms", "MMS link", "", 7),
    ("describe_error", "describe_error", "", 8),
]


def _title_source_label(row: PostcoordRow) -> str:
    if row.title_source == "foundation_entity":
        return '<span class="own">has Foundation code</span>'
    return '<span class="composed">composed (no Foundation code)</span>'


def _foundation_cell(row: PostcoordRow) -> str:
    if not row.foundation_entity_id:
        return '<span class="dash">—</span>'
    esc = html.escape
    if row.foundation_browser_link:
        return f'<a href="{esc(row.foundation_browser_link)}" target="_blank">{esc(row.foundation_entity_id)}</a>'
    return esc(row.foundation_entity_id)


def _mms_cell(row: PostcoordRow) -> str:
    esc = html.escape
    links = []
    if row.browse_url:
        links.append(f'<a href="{esc(row.browse_url)}" target="_blank">pub</a>')
    if row.browser_link_local:
        links.append(f'<a href="{esc(row.browser_link_local)}" target="_blank">loc</a>')
    return " / ".join(links) if links else '<span class="dash">—</span>'


def _row_html(row: PostcoordRow) -> str:
    esc = html.escape
    css_class = ' class="rejected"' if row.describe_status != "ok" else ""
    extension_title = esc(" | ".join(row.extension_codes))
    data = (
        f' data-status="{esc(row.describe_status)}"'
        f' data-foundation="{1 if row.has_own_entity else 0}"'
        f' data-multistem="{1 if row.is_multi_stem else 0}"'
        f' data-ext="{1 if row.has_extension_code else 0}"'
    )
    return (
        f"<tr{css_class}{data}>"
        f'<td class="code">{esc(row.code)}</td>'
        f'<td class="title">{esc(row.title)}</td>'
        f"<td>{_title_source_label(row)}</td>"
        f"<td>{esc(row.describe_status)}</td>"
        f"<td>{2 if row.is_multi_stem else 1}</td>"
        f'<td title="{extension_title}">{row.extension_count}</td>'
        f'<td class="entity" title="{esc(row.entity_id)}">{esc(row.entity_id)}</td>'
        f"<td>{_foundation_cell(row)}</td>"
        f"<td>{_mms_cell(row)}</td>"
        f'<td title="{esc(row.describe_error)}">{esc(row.describe_error)}</td>'
        "</tr>"
    )


def render_review_html(
    rows: list[PostcoordRow], *, release: str, total_indexed: int, total_ok: int, total_rejected: int,
    total_own_entity: int,
) -> str:
    """One self-contained, dense HTML page: select-based AND filters, a live visible/total counter."""
    rows_html = "".join(_row_html(row) for row in rows)
    colgroup = "".join(f'<col style="width:{width}%">' for _, _, _, width in COLUMNS)
    header_cells = "".join(f'<th class="{css}">{html.escape(label)}</th>' for _, label, css, _ in COLUMNS)
    total_multi_stem = sum(1 for row in rows if row.is_multi_stem)
    total_with_ext = sum(1 for row in rows if row.has_extension_code)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>ICD-11 {html.escape(release)} — indexed post-coordinated codes</title>
<style>{STYLE}</style></head>
<body>
<h1>ICD-11 {html.escape(release)} — indexed post-coordinated codes</h1>
<div class="meta">
  Source: WHO ICD-API search index (release {html.escape(release)}), via
  <code>ciel-scripts/run_icd_api_postcoord_index_export.sh</code> (read-only reference; not imported by
  ocl-content). Three WHO post-coordination concepts, not one: <b>Stem code</b> (the root code,
  generally a diagnosis — "Stem code(s)" is 2 only when a <i>second</i> stem is also present, a
  <code>/</code> component, which is different from an extension); <b>Extension code</b> (a value
  after a stem's <code>&amp;</code> — laterality, severity, causing agent, etc.; a composite can carry
  none, one, or several); <b>Foundation code</b> (WHO's own registered entity — set on a composite row
  when the <i>whole expression itself</i>, not just one of its parts, has its own Foundation entity).
  <b>Title source</b>: <span class="own">has Foundation code</span> when
  <code>/describe</code>'s <code>foundationUri</code> resolves to that entity, else
  <span class="composed">composed (no Foundation code)</span> — the title was only assembled from the
  stem + extension titles. <b>Describe</b>: <code>ok</code> or <code>rejected_by_api</code> (rejected
  rows highlighted red). <b>Foundation code</b> column links to that entity's own page
  (<code>.../foundation/en#&lt;id&gt;</code>) when one exists — "—" otherwise. That page proves the
  expression is registered, with its own title/definition/synonyms, but does <b>not</b> show it
  combined with its stem. <b>MMS link</b> (<i>pub</i>/<i>loc</i>) is what shows the combination: it
  opens the first stem's MMS page with the Postcoordination panel pre-selecting these exact values —
  works for every composite, Foundation code or not; <i>pub</i> is the public <code>icd.who.int</code>
  reconstruction, <i>loc</i> the local ICD-API container's own link (reachable only while it runs).<br>
  Total indexed: <span class="count">{total_indexed:,}</span> |
  ok: {total_ok:,} | rejected: {total_rejected:,} |
  Foundation code: {total_own_entity:,} | multi-stem: {total_multi_stem:,} | with extension: {total_with_ext:,}.
</div>
<div class="toolbar">
  <label>Text
    <input id="filter" type="text" placeholder="code, title, composite URI…">
  </label>
  <label>Describe status
    <select id="f-status"><option value="all">All</option><option value="ok">ok</option><option value="rejected_by_api">rejected_by_api</option></select>
  </label>
  <label>Foundation code
    <select id="f-foundation"><option value="all">All</option><option value="1">With (registered entity)</option><option value="0">Without (composed only)</option></select>
  </label>
  <label>Stem code(s)
    <select id="f-multistem"><option value="all">All</option><option value="0">1 (single stem)</option><option value="1">2 (second stem present)</option></select>
  </label>
  <label>Extension code(s)
    <select id="f-ext"><option value="all">All</option><option value="1">With</option><option value="0">Without</option></select>
  </label>
  <span id="count"></span>
</div>
<table id="tbl">
<colgroup>{colgroup}</colgroup>
<thead><tr>{header_cells}</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
<script>
const textFilter = document.getElementById('filter');
const selectIds = ['f-status', 'f-foundation', 'f-multistem', 'f-ext'];
const selects = selectIds.map(id => document.getElementById(id));
const rows = Array.from(document.querySelectorAll('#tbl tbody tr'));
const counter = document.getElementById('count');
const total = rows.length;

// Every active control narrows the result further (AND, not OR): each added filter can only
// remove rows from what the other filters already kept, never add rows back.
function applyFilters() {{
  const q = textFilter.value.toLowerCase();
  const [status, foundation, multistem, ext] = selects.map(s => s.value);
  let visible = 0;
  rows.forEach(r => {{
    const matches = (status === 'all' || r.dataset.status === status)
      && (foundation === 'all' || r.dataset.foundation === foundation)
      && (multistem === 'all' || r.dataset.multistem === multistem)
      && (ext === 'all' || r.dataset.ext === ext)
      && (q === '' || r.textContent.toLowerCase().includes(q));
    r.style.display = matches ? '' : 'none';
    if (matches) visible++;
  }});
  counter.textContent = `Showing ${{visible.toLocaleString()}} of ${{total.toLocaleString()}}`;
}}

textFilter.addEventListener('input', applyFilters);
selects.forEach(s => s.addEventListener('change', applyFilters));
applyFilters();
</script>
</body></html>
"""


def write_review_html(path: Path, rows: list[PostcoordRow], **kwargs) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_html(rows, **kwargs), encoding="utf-8")
