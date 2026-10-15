"""Reader for the indexed post-coordinated ICD-11 codes (an add-on layer over the base Source).

The input is the *full* CSV produced by the sibling ``ciel-scripts`` repository's
``list_postcoordinated_index_codes.py --full-csv`` (via ``run_icd_api_postcoord_index_export.sh``):
one row per composite code already served by the local WHO ICD-API search index for one release,
hydrated with one ``/describe`` call per code and one Foundation entity call per own entity id. That
script is read-only reference; nothing here imports it, and its CSV is **not** committed to this
repository (it is generated locally from a WHO ICD-API Docker container, not a WHO-published file) —
the path is supplied on the command line at build time.

"Indexed" is not "valid": the API's own value-set rules (``/describe``) reject some composites the
index still serves (``describe_status=rejected_by_api``). By default this reader keeps only the
``ok`` rows; ``include_rejected=True`` keeps all of them, each still carrying its ``describe_status``
and ``describe_error`` so they can be filtered or audited after load. See
``terminologies/who/icd-11/README.md`` for the review artifact that lists the rejected rows with
their WHO browser links.

The first stem code — the prefix of the composite ``code`` before its first ``&`` or ``/`` — is
derived from the composite string itself, not from the CSV's own ``stem_code`` column: that column
comes from the hydration call and is empty for every rejected row, while the composite string always
carries its first component verbatim regardless of hydration outcome.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

LIST_SEPARATOR = " | "
STEM_SEPARATOR_RE = re.compile(r"[&/]")
NUMERIC_ID_RE = re.compile(r"/mms/(\d+)(?:/[a-z]+)?")
TOP_LEVEL_SEPARATOR_RE = re.compile(r"\s([&/])\s")
REQUIRED_COLUMNS = (
    "entity_id", "code", "title", "describe_status", "describe_error",
    "axes", "extension_codes", "extension_labels",
    "browser_link", "title_source", "foundation_entity_id", "foundation_browser_link",
)


def first_stem_code(code: str) -> str:
    """The composite code's first component, e.g. ``1A00`` from ``1A00&XN62R`` or ``5B81.Y/1A00``."""
    return STEM_SEPARATOR_RE.split(code, maxsplit=1)[0]


def public_browse_url(entity_id: str, release: str) -> str:
    """Reconstruct the public ``icd.who.int`` browser link from the composite's Linearization URIs.

    Not a WHO-supplied field for post-coordinated terms: the index only carries ``entity_id`` (the
    composite URI) and a *local* ICD-API container browse link. This pipeline rebuilds the public
    link against the same anchor scheme the WHO browser uses, so it is documented as a derived
    field (``BrowseURL``), never attributed to WHO as a verbatim column.
    """
    ids = NUMERIC_ID_RE.findall(entity_id or "")
    if not ids:
        return ""
    separators = TOP_LEVEL_SEPARATOR_RE.findall(entity_id)
    anchor = ids[0]
    for separator, next_id in zip(separators, ids[1:]):
        anchor += f"%20{'%26' if separator == '&' else '%2F'}%20{next_id}"
    return f"https://icd.who.int/browse/{release}/mms/en#{anchor}"


@dataclass(frozen=True)
class PostcoordRow:
    code: str
    title: str
    entity_id: str
    stem_code: str
    axes: tuple[str, ...]
    extension_codes: tuple[str, ...]
    extension_labels: tuple[str, ...]
    describe_status: str
    describe_error: str
    browse_url: str
    source_row: int
    browser_link_local: str = ""
    title_source: str = ""
    foundation_entity_id: str = ""
    foundation_browser_link: str = ""

    @property
    def is_multi_stem(self) -> bool:
        """True when the composite carries a second stem (a ``/`` component), not just extensions."""
        return "/" in self.code

    @property
    def extension_count(self) -> int:
        """Number of extension values, counted from the code's own ``&`` separators.

        Deliberately NOT derived from the hydrated ``extension_codes``/``axes`` columns: ``/describe``
        does not reliably decompose every composite into axis values. Confirmed against two concrete
        rows from the real capture — ``2D10.Y&XH3Z50`` (a true extension after ``&``) hydrates to an
        EMPTY ``extension_codes``, because this composite already has its own registered Foundation
        entity and ``/describe`` stops decomposing it; and ``1A02/1G40`` (a second stem, no ``&`` at
        all) hydrates to a NON-empty ``extension_codes`` of ``1G40``, because ``/describe`` reported
        the second stem itself as an ``hasManifestation`` axis value. The code string's own ``&``
        count is the only signal that holds for every row regardless of hydration outcome.
        """
        return self.code.count("&")

    @property
    def has_extension_code(self) -> bool:
        return self.extension_count > 0

    @property
    def has_own_entity(self) -> bool:
        return bool(self.foundation_entity_id)


@dataclass
class PostcoordIndex:
    release: str
    rows: list[PostcoordRow] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    total_read: int = 0


def _split_list(value: str) -> tuple[str, ...]:
    return tuple(part for part in (value or "").split(LIST_SEPARATOR) if part)


def _open_text(path: Path) -> io.TextIOWrapper:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"post-coordinated index CSV not found: {path}")
    return path.open("r", encoding="utf-8-sig", newline="")


def read(path: Path, *, release: str, include_rejected: bool = False) -> PostcoordIndex:
    """Read the full CSV into ordered, deduplicated rows, keeping only ``ok`` rows unless asked."""
    index = PostcoordIndex(release=release)
    seen: set[str] = set()
    with _open_text(path) as stream:
        reader = csv.DictReader(stream)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        for number, raw in enumerate(reader, start=2):
            index.total_read += 1
            code = (raw.get("code") or "").strip()
            status = (raw.get("describe_status") or "").strip()
            if not code:
                index.skipped.append({"reason": "no-code", "source_row": number})
                continue
            if status != "ok" and not include_rejected:
                index.skipped.append({"reason": f"describe_status={status or 'unknown'}", "source_row": number})
                continue
            if code in seen:
                index.skipped.append({"reason": "duplicate-code", "source_row": number, "code": code})
                continue
            seen.add(code)
            entity_id = (raw.get("entity_id") or "").strip()
            index.rows.append(
                PostcoordRow(
                    code=code,
                    title=(raw.get("title") or code).strip(),
                    entity_id=entity_id,
                    stem_code=first_stem_code(code),
                    axes=_split_list(raw.get("axes", "")),
                    extension_codes=_split_list(raw.get("extension_codes", "")),
                    extension_labels=_split_list(raw.get("extension_labels", "")),
                    describe_status=status,
                    describe_error=(raw.get("describe_error") or "").strip(),
                    browse_url=public_browse_url(entity_id, release),
                    source_row=number,
                    browser_link_local=(raw.get("browser_link") or "").strip(),
                    title_source=(raw.get("title_source") or "").strip(),
                    foundation_entity_id=(raw.get("foundation_entity_id") or "").strip(),
                    foundation_browser_link=(raw.get("foundation_browser_link") or "").strip(),
                )
            )
    return index
