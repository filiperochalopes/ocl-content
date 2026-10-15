"""Stdlib reader for the WHO ICD-API search index (``ix_*_foundation-*mms_*.pbf``).

The index is a protobuf file the ``whoicd/icd-api`` container loads at boot. This module reads only
what the build needs: for every indexed *composite* (post-coordinated) entry of one release, the
Foundation entities the index attaches to it, each with its own title and its synonyms. It is a
stdlib port of ``decode_index_entities`` from the sibling ``ciel-scripts`` repository
(``list_postcoordinated_index_codes.py``), which stays read-only reference and is never imported.

The layout is reverse engineered (index format v5.7), so every structural surprise raises
``ValueError`` instead of returning a partial result:

- root field 10: SharedIndexInfo (field 10 = label, field 11 = Foundation entity id);
- root field 11: linearization table (field 10 -> field 10 = SharedIndexInfo number);
- root field 93: index id -> position of its SingleIndex in root field 90;
- SingleIndex field 2: IndexInfo records. A composite's record points at its label, directly or
  through the linearization table. A record whose TitleIndexInfoNo is its own position carries the
  entity's title; the other records with that TitleIndexInfoNo are its synonyms. One composite can
  represent several Foundation entities.

A protobuf field that equals zero is omitted on the wire, so an absent ``TitleIndexInfoNo`` means 0.
The index is an external, generated file: it is passed by path at build time and is not committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

LINEARIZATION_OFFSET = 536870911  # SharedGenericIndexInfoNumber: points into the linearization table
VIRTUAL_OFFSET = 1073741823  # ... or into the virtual (post-coordinated) table


@dataclass(frozen=True)
class IndexEntity:
    """One Foundation entity that the index attaches to a composite entry."""

    foundation_id: str
    title: str
    synonyms: tuple[str, ...]


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated protobuf varint")
        byte = buf[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not byte & 0x80:
            return result, pos
        shift += 7


def _iter_fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield (field number, wire type, value) of a protobuf message; value is int or bytes."""
    pos, end = 0, len(buf)
    while pos < end:
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            if pos + length > end:
                raise ValueError("truncated protobuf field: declared length exceeds the message")
            value, pos = buf[pos : pos + length], pos + length
        elif wire == 5:
            value, pos = buf[pos : pos + 4], pos + 4
        elif wire == 1:
            value, pos = buf[pos : pos + 8], pos + 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield field, wire, value


def _submessage_varint(buf: bytes, outer_field: int, inner_field: int) -> int | None:
    for field, wire, value in _iter_fields(buf):
        if field == outer_field and wire == 2:
            for inner, inner_wire, inner_value in _iter_fields(value):
                if inner == inner_field and inner_wire == 0:
                    return inner_value
    return None


def _parse_index_info(record: bytes) -> tuple[int | None, int, str]:
    """(SharedIndexInfoNo, TitleIndexInfoNo, composite URI) of one IndexInfo record."""
    shared_no: int | None = None
    title_no = 0
    uri = ""
    for field, wire, value in _iter_fields(record):
        if field == 5 and wire == 2:
            for inner, inner_wire, inner_value in _iter_fields(value):
                if inner == 10 and inner_wire == 0:
                    shared_no = inner_value
        elif field == 9 and wire == 0:
            title_no = value
        elif field == 100 and wire == 2:
            for inner, inner_wire, inner_value in _iter_fields(value):
                if inner == 6 and inner_wire == 2:
                    uri = inner_value.decode("utf-8", "replace")
    return shared_no, title_no, uri


def decode_index_entities(data: bytes, release: str) -> dict[str, list[IndexEntity]]:
    """Map every composite URI string of ``{release}_MMS`` to its Foundation entities, in index order."""
    shared: list[tuple[str, int | None]] = []
    linearization: list[int | None] = []
    sections: list[bytes] = []
    index_numbers: dict[str, int] = {}
    for field, wire, value in _iter_fields(data):
        if wire != 2:
            continue
        if field == 10:
            label, foundation_no = "", None
            for inner, inner_wire, inner_value in _iter_fields(value):
                if inner == 10 and inner_wire == 2:
                    label = inner_value.decode("utf-8", "replace")
                elif inner == 11 and inner_wire == 0:
                    foundation_no = inner_value
            shared.append((label, foundation_no))
        elif field == 11:
            linearization.append(_submessage_varint(value, 10, 10))
        elif field == 90:
            sections.append(value)
        elif field == 93:
            name, number = "", 0  # protobuf omits a zero value
            for inner, inner_wire, inner_value in _iter_fields(value):
                if inner == 1 and inner_wire == 2:
                    name = inner_value.decode("utf-8", "replace")
                elif inner == 2 and inner_wire == 0:
                    number = inner_value
            index_numbers[name] = number

    section_no = index_numbers.get(f"{release}_MMS")
    if section_no is None or section_no >= len(sections):
        raise ValueError(f"index file has no {release}_MMS section (found: {sorted(index_numbers)})")

    def label_of(shared_no: int | None) -> tuple[str, int | None]:
        if shared_no is None or shared_no >= VIRTUAL_OFFSET:
            return "", None
        if shared_no >= LINEARIZATION_OFFSET:
            position = shared_no - LINEARIZATION_OFFSET
            shared_no = linearization[position] if position < len(linearization) else None
        if shared_no is None or shared_no >= len(shared):
            return "", None
        return shared[shared_no]

    entities: dict[str, dict[int, dict[str, Any]]] = {}
    records = [value for field, wire, value in _iter_fields(sections[section_no]) if field == 2 and wire == 2]
    for position, record in enumerate(records):
        shared_no, title_no, uri = _parse_index_info(record)
        if not (" & " in uri or " / " in uri):
            continue
        label, foundation_no = label_of(shared_no)
        entity = entities.setdefault(uri, {}).setdefault(
            title_no, {"foundation_id": "", "title": "", "synonyms": []}
        )
        if not label:
            continue
        if position == title_no:
            entity["title"] = label
            entity["foundation_id"] = str(foundation_no) if foundation_no is not None else ""
        elif label not in entity["synonyms"]:
            entity["synonyms"].append(label)
    return {
        uri: [
            IndexEntity(e["foundation_id"], e["title"], tuple(e["synonyms"]))
            for _, e in sorted(by_title.items())
            if e["title"] and e["foundation_id"]
        ]
        for uri, by_title in entities.items()
    }


def read_index_entities(path: Path, release: str) -> dict[str, list[IndexEntity]]:
    """Read the index file at ``path`` (never modified) and decode its composite entities."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"ICD-API search index file not found: {path}")
    return decode_index_entities(path.read_bytes(), release)


def entity_names(entities: list[IndexEntity] | tuple[IndexEntity, ...]) -> tuple[str, ...]:
    """Titles then synonyms of every entity, in index order, without exact repeats."""
    names: list[str] = []
    for entity in entities:
        for name in (entity.title, *entity.synonyms):
            if name and name not in names:
                names.append(name)
    return tuple(names)
