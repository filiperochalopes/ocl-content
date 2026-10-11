#!/usr/bin/env python3
"""Turn an OCL Source export into a replica seed: the Source configuration plus ordered bulk-import parts.

    python3 tools/ocl_replica_seed.py --export exports/prod/WHO_ICD-10-WHO_HEAD.zip \\
        --out-dir exports/replica/WHO_ICD-10-WHO

It reads a file and writes files; it makes no network call and uploads nothing. Use it to rehearse an
update on a local OCL instance that mirrors production:

1. ``source.create.json`` is the body that creates the Source with the same configuration as the
   export's header (name, description, locales, access, canonical URL, ...). Create the Source with it
   by hand, or have a person with the right access do so.
2. ``replica_part_001.ndjson`` ... are the concepts (then the mappings), in an order OCL can import:
   every parent before its children. Upload them **by hand, in numeric order, with one Queue ID**.
3. ``post_import.patch.json`` holds the hierarchy settings. The root concept must exist first, so apply
   it only after the import task has finished.
4. ``replica_manifest.json`` records the export's SHA-256, the counts, and every part's SHA-256.

Unlike a generic "copy a Source" conversion, no ``Source`` or ``Organization`` line is emitted into the
parts: a bulk-import ``Source`` line would rename the replica and add ``extras``, and the point here is a
faithful copy. The output is deterministic (no timestamp, no absolute path).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocl_artifacts  # noqa: E402
import ocl_export  # noqa: E402

CONCEPT_FIELDS = (
    "id", "external_id", "concept_class", "datatype", "names", "descriptions",
    "extras", "retired", "retire_reason", "parent_concept_urls",
)
NAME_FIELDS = ("name", "external_id", "locale", "locale_preferred", "name_type", "retired", "retire_reason")
DESCRIPTION_FIELDS = (
    "description", "external_id", "locale", "locale_preferred", "description_type", "retired", "retire_reason",
)
MAPPING_FIELDS = (
    "id", "external_id", "map_type", "retired", "retire_reason", "sort_weight", "extras",
    "from_concept_code", "from_concept_url", "from_source_url",
    "to_concept_code", "to_concept_name", "to_concept_url", "to_source_url",
)
# Configuration of a Source that can be sent when creating it. Server-owned fields (uuid, urls, dates,
# checksums, counters) are deliberately absent, and so are the two hierarchy settings: the root concept
# does not exist yet when the Source is created (see post_import.patch.json).
SOURCE_CREATE_FIELDS = (
    "id", "short_code", "name", "full_name", "description", "source_type", "default_locale", "supported_locales",
    "public_access", "canonical_url", "custom_validation_schema", "website", "external_id", "content_type",
    "case_sensitive", "compositional", "version_needed", "jurisdiction", "identifier", "contact", "publisher",
    "purpose", "copyright", "revision_date", "text", "experimental", "meta", "properties", "filters",
    "autoid_concept_mnemonic", "autoid_concept_external_id", "autoid_concept_name_external_id",
    "autoid_concept_description_external_id", "autoid_mapping_mnemonic", "autoid_mapping_external_id",
    "autoid_concept_mnemonic_start_from", "autoid_concept_external_id_start_from",
    "autoid_mapping_mnemonic_start_from", "autoid_mapping_external_id_start_from",
)
HIERARCHY_FIELDS = ("hierarchy_root_url", "hierarchy_meaning")
CONCEPT_PATH = re.compile(r"/concepts/([^/]+)/")
# A parent URL in an export may carry the parent's VERSION id (/concepts/B00-B09/14269827/). That id is
# a row of the exporting server's database and means nothing on another instance, so the seed links to
# the concept itself (/concepts/B00-B09/).
VERSIONED_CONCEPT_URL = re.compile(r"^(/(?:orgs|users)/[^/]+/sources/[^/]+/concepts/[^/]+/)[^/]+/$")
SIZE_RE = re.compile(r"^(\d+)(b|kb|mb|gb)?$", re.IGNORECASE)


def parse_size(text: str) -> int:
    match = SIZE_RE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 2mb)")
    unit = (match.group(2) or "b").lower()
    return int(match.group(1)) * {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}[unit]


def empty(value) -> bool:
    return value is None or value in ("", [], {})


def pick(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: row[field] for field in fields if field in row and row[field] is not None}


def source_create_body(header: dict) -> dict:
    """The configuration to create the Source with, copied from the export header."""
    body = {field: header[field] for field in SOURCE_CREATE_FIELDS if field in header and not empty(header[field])}
    # In an export header ``id`` and ``version`` name the VERSION (for example "HEAD"); the Source's own
    # mnemonic is ``short_code``.
    if header.get("short_code"):
        body["id"] = header["short_code"]
    extras = {k: v for k, v in (header.get("extras") or {}).items() if not str(k).startswith("__")}
    if extras:  # keys such as __export_time are artifacts of generating the export, not configuration
        body["extras"] = extras
    return body


def normalize_parent_urls(urls: list[str]) -> list[str]:
    """Drop version ids from parent URLs and collapse parents that become identical, keeping order."""
    unique: list[str] = []
    for url in urls or []:
        match = VERSIONED_CONCEPT_URL.match(url)
        base = match.group(1) if match else url
        if base not in unique:
            unique.append(base)
    return unique


def concept_line(row: dict, owner: str, source: str) -> dict:
    line = {"type": "Concept", **pick(row, CONCEPT_FIELDS)}
    if "parent_concept_urls" in line:
        line["parent_concept_urls"] = normalize_parent_urls(line["parent_concept_urls"])
    line["names"] = [pick(n, NAME_FIELDS) for n in row.get("names") or [] if isinstance(n, dict)]
    descriptions = [pick(d, DESCRIPTION_FIELDS) for d in row.get("descriptions") or [] if isinstance(d, dict)]
    if descriptions:
        line["descriptions"] = descriptions
    else:
        line.pop("descriptions", None)
    line.update({"owner": owner, "owner_type": "Organization", "source": source})
    return line


def mapping_line(row: dict, owner: str, source: str) -> dict:
    return {"type": "Mapping", **pick(row, MAPPING_FIELDS), "owner": owner, "owner_type": "Organization", "source": source}


def parent_ids(line: dict) -> list[str]:
    ids = []
    for url in line.get("parent_concept_urls") or []:
        match = CONCEPT_PATH.search(url)
        ids.append(unquote(match.group(1)) if match else url)
    return ids


def order_parents_first(lines: list[dict]) -> tuple[list[dict], dict]:
    """Stable topological order: a concept is emitted after every parent that is in the set."""
    by_id = {line["id"]: line for line in lines}
    emitted: set[str] = set()
    ordered: list[dict] = []
    reordered = 0
    state: dict[str, int] = {}

    def visit(concept_id: str, path: list[str]) -> None:
        if concept_id in emitted:
            return
        if state.get(concept_id) == 1:
            raise ValueError(f"hierarchy cycle through {' -> '.join(path + [concept_id])}")
        state[concept_id] = 1
        for parent in parent_ids(by_id[concept_id]):
            if parent in by_id:
                visit(parent, path + [concept_id])
        state[concept_id] = 2
        emitted.add(concept_id)
        ordered.append(by_id[concept_id])

    original_position = {line["id"]: index for index, line in enumerate(lines)}
    for line in lines:
        visit(line["id"], [])
    reordered = sum(1 for index, line in enumerate(ordered) if original_position[line["id"]] != index)
    external = sum(1 for line in lines for parent in parent_ids(line) if parent not in by_id)
    orphans = [line["id"] for line in lines if not parent_ids(line)]
    return ordered, {"concepts_moved": reordered, "parents_outside_the_set": external, "ids_without_parent": orphans}


def read_export(path: Path) -> dict:
    document = json.loads(ocl_export.read_bytes(path).decode("utf-8-sig"))
    if not isinstance(document, dict) or not isinstance(document.get("concepts"), list):
        raise ValueError(f"{path}: not a Source version export (a JSON object with a 'concepts' list)")
    return document


def build(export: dict, owner: str, source: str) -> dict:
    rows = [row for row in export["concepts"] if isinstance(row, dict)]
    concepts = [concept_line(row, owner, source) for row in rows]
    versioned = sum(1 for row in rows for url in row.get("parent_concept_urls") or [] if VERSIONED_CONCEPT_URL.match(url))
    collapsed = [line["id"] for row, line in zip(rows, concepts)
                 if len(row.get("parent_concept_urls") or []) != len(line.get("parent_concept_urls") or [])]
    ids = [line["id"] for line in concepts]
    if len(ids) != len(set(ids)):
        raise ValueError("the export repeats a concept id")
    ordered, ordering = order_parents_first(concepts)
    mappings = [mapping_line(row, owner, source) for row in export.get("mappings") or [] if isinstance(row, dict)]
    header = {k: v for k, v in export.items() if k not in ("concepts", "mappings", "references")}
    return {
        "lines": ordered + mappings,
        "source_create": source_create_body(header),
        "post_import": {k: header[k] for k in HIERARCHY_FIELDS if not empty(header.get(k))},
        "counts": {"concepts": len(ordered), "mappings": len(mappings),
                   "references_not_copied": len(export.get("references") or [])},
        "ordering": ordering,
        "parent_urls": {"unversioned": versioned, "concepts_with_duplicate_parents_collapsed": collapsed},
    }


def write_outputs(result: dict, out_dir: Path, export_path: Path, max_part_bytes: int) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = ocl_artifacts.write_parts(out_dir, result["lines"], max_part_bytes, stem="replica_part")
    ocl_artifacts.write_json(out_dir / "source.create.json", result["source_create"])
    ocl_artifacts.write_json(out_dir / "post_import.patch.json", result["post_import"])
    manifest = {
        "schema_version": 1,
        "input": {"file": Path(export_path).name, "sha256": ocl_export.sha256_path(export_path)},
        "counts": result["counts"],
        "ordering": result["ordering"],
        "parent_urls": result["parent_urls"],
        "files": {"source_create": "source.create.json", "post_import_patch": "post_import.patch.json"},
        "parts": [part.__dict__ for part in parts],
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": ("Create the Source with source.create.json, upload the part ZIPs (replica_part_NNN.zip, each within "
                     "the compressed part cap) in numeric order with one Queue ID, wait for the import task, then apply "
                     "post_import.patch.json."),
        },
    }
    ocl_artifacts.write_json(out_dir / "replica_manifest.json", manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", type=Path, required=True, help="Source version export (.zip or export.json)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--owner", help="owner of the replica (default: the export's owner)")
    parser.add_argument("--source", help="Source id of the replica (default: the export's Source)")
    parser.add_argument("--max-part-size", type=parse_size, default=ocl_artifacts.DEFAULT_PART_BYTES, metavar="SIZE",
                        help="cap on the COMPRESSED size of each part's upload ZIP (default 2mb)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        export = read_export(args.export)
        owner = args.owner or export.get("owner")
        source = args.source or export.get("short_code") or export.get("source")
        if not owner or not source:
            raise ValueError("the export names no owner or Source; pass --owner and --source")
        result = build(export, owner, source)
        manifest = write_outputs(result, args.out_dir, args.export, args.max_part_size)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    counts = manifest["counts"]
    print(f"replica of /orgs/{owner}/sources/{source}/ from {args.export.name}")
    print(f"  {counts['concepts']:,} concepts, {counts['mappings']:,} mappings, "
          f"{counts['references_not_copied']:,} references not copied")
    print(f"  ordering: {manifest['ordering']}")
    print(f"  parent URLs: {manifest['parent_urls']}")
    for part in manifest["parts"]:
        print(f"  {part['zip']}  {part['lines']:,} lines  {part['bytes']:,} bytes -> {part['zip_bytes']:,} bytes zipped")
    print(f"  Source configuration: {args.out_dir / 'source.create.json'}")
    print(f"  after the import: {args.out_dir / 'post_import.patch.json'}")
    print("  upload is manual: parts in numeric order, one Queue ID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
