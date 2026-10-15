"""ICD-11 base Source: Simple Tabulation to versioned bulk-import artifacts.

    # fetch the pinned WHO release (verified by SHA-256; never committed)
    python3 terminologies/who/icd-11/pipeline/cli.py fetch-assets

    # build ordered parts, the full bundle, and the two hand-off ZIPs
    python3 terminologies/who/icd-11/pipeline/cli.py build

Uploading is manual and stays manual. This CLI makes no network call apart from ``fetch-assets``
(a public, hash-verified download) and never calls an OCL write, import, or upload endpoint. The
`.bundle.zip` contains exactly one full-bundle NDJSON file. The `.parts.zip` is a distribution
wrapper; extract it and upload each inner one-member part ZIP in order, never the wrapper itself.
"""

from __future__ import annotations

import argparse
from collections import Counter
import re
import sys
from pathlib import Path

# The pipeline is imported by path (tools/ocl_pipeline_loader.py), never as a top-level ``pipeline``,
# so another terminology's ``pipeline`` package cannot shadow this one in the same process.
_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from ocl_pipeline_loader import load  # noqa: E402

TERMINOLOGY = "who/icd-11"


def _pipeline(module: str):
    return load(TERMINOLOGY, module)


asset_registry = _pipeline("assets")
simple_tabulation = _pipeline("simple_tabulation")
postcoordinated = _pipeline("postcoordinated")
flat_synonyms = _pipeline("flat_synonyms")
foundation_index = _pipeline("foundation_index")
review = _pipeline("review")
_bulk = _pipeline("build_bulkimport")
TARGET_OWNER, TARGET_SOURCE, build = _bulk.TARGET_OWNER, _bulk.TARGET_SOURCE, _bulk.build
build_postcoordinated = _bulk.build_postcoordinated

from ocl_artifacts import (  # noqa: E402
    upload_ready_map,
    DEFAULT_METHOD,
    DEFAULT_PART_BYTES,
    METHODS,
    build_manifest,
    create_archive,
    sha256_file,
    write_bundle,
    write_json,
    write_parts,
)

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TERMINOLOGY_DIR.parents[2]
ASSETS_DIR = TERMINOLOGY_DIR / "assets"
DEFAULT_INPUT = ASSETS_DIR / "who" / "2026-01" / "SimpleTabulation-ICD-11-MMS-en.zip"
DEFAULT_OUTPUT_DIR = TERMINOLOGY_DIR / "output" / "staging"
DEFAULT_PRODUCTION_OUTPUT_DIR = TERMINOLOGY_DIR / "output" / "production"
DEFAULT_BUNDLE_ARCHIVE = "bulkimport_icd11-who.bundle.zip"
DEFAULT_PARTS_ARCHIVE = "bulkimport_icd11-who.parts.zip"
LEGACY_ARCHIVE = "bulkimport_icd11-who.zip"
SIZE_RE = re.compile(r"^(\d+)(b|kb|mb|gb)?$", re.IGNORECASE)


def parse_size(text: str) -> int:
    match = SIZE_RE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 2mb)")
    unit = (match.group(2) or "b").lower()
    return int(match.group(1)) * {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}[unit]


def display_path(path: Path) -> str:
    """Repo-relative POSIX path for provenance records; a path outside the repo keeps only its name."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch-assets", help="download and verify the pinned Simple Tabulation")
    fetch.add_argument("--assets-dir", type=Path, default=ASSETS_DIR)
    fetch.add_argument("--force", action="store_true", help="re-download even when a verified copy exists")

    build_parser = subparsers.add_parser("build", help="write the bulk-import parts, bundle, audit, and both hand-off ZIPs")
    build_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Simple Tabulation .zip or .txt")
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE",
        help="cap on the COMPRESSED size of each part's upload ZIP (default 2mb)")
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE, help="single-member full-bundle ZIP")
    build_parser.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE, help="distribution ZIP containing each upload-part ZIP")
    build_parser.add_argument("--no-archive", action="store_true", help="skip both hand-off ZIPs (parts and bundle remain)")
    build_parser.add_argument(
        "--flat-synonyms", type=Path,
        help="flat_foundation_synonyms.csv from ciel-scripts' list_flat_foundation_synonyms.py (external; not committed): "
             "adds each Foundation title as an untyped name of its stem/extension code",
    )
    build_parser.add_argument(
        "--postcoordinated-csv", type=Path,
        help="full CSV from ciel-scripts' list_postcoordinated_index_codes.py --full-csv (external; not committed): "
             "appends the post-coordinated concepts and their NARROWER-THAN mappings to this same bundle; needs --index-file",
    )
    build_parser.add_argument(
        "--index-file", type=Path,
        help="WHO ICD-API search index (ix_*mms*.pbf, read-only, external) that supplies the post-coordinated aliases; "
             "needs --postcoordinated-csv",
    )
    build_parser.add_argument("--include-rejected", action="store_true",
        help="with --postcoordinated-csv, also build describe_status=rejected_by_api rows (excluded by default)")

    production = subparsers.add_parser(
        "build-production",
        help="PRODUCTION profile: base Simple Tabulation load ONLY — no aliases, no post-coordinated "
             "layer (those require decoding the WHO ICD-API search index / inspecting /describe, a "
             "reverse-engineering risk under the ICD-11 licence; staging-only, see README)",
    )
    production.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Simple Tabulation .zip or .txt")
    production.add_argument("--output-dir", type=Path, default=DEFAULT_PRODUCTION_OUTPUT_DIR)
    production.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE",
        help="cap on the COMPRESSED size of each part's upload ZIP (default 2mb)")
    production.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    production.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE, help="single-member full-bundle ZIP")
    production.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE, help="distribution ZIP containing each upload-part ZIP")
    production.add_argument("--no-archive", action="store_true", help="skip both hand-off ZIPs (parts and bundle remain)")

    postcoord = subparsers.add_parser(
        "build-postcoordinated",
        help="additive layer: concepts + NARROWER-THAN mappings for indexed post-coordinated codes",
    )
    postcoord.add_argument(
        "--input", type=Path, required=True,
        help="full CSV from ciel-scripts' list_postcoordinated_index_codes.py --full-csv (external; not committed)",
    )
    postcoord.add_argument(
        "--simple-tabulation", type=Path, default=DEFAULT_INPUT,
        help="base Simple Tabulation, to resolve known stem ids and the release label",
    )
    postcoord.add_argument("--include-rejected", action="store_true",
        help="also build the describe_status=rejected_by_api rows (excluded by default; see README)")
    postcoord.add_argument("--index-file", type=Path,
        help="WHO ICD-API search index (read-only, external): adds each composite's Foundation titles and synonyms as untyped names")
    postcoord.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "postcoordinated")
    postcoord.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    postcoord.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    postcoord.add_argument("--archive-name", default="bulkimport_icd11-who-postcoord.bundle.zip")
    postcoord.add_argument("--parts-archive-name", default="bulkimport_icd11-who-postcoord.parts.zip")
    postcoord.add_argument("--no-archive", action="store_true")

    review = subparsers.add_parser(
        "review",
        help="standalone, dense HTML: every indexed post-coordinated code, title source, describe status",
    )
    review.add_argument("--input", type=Path, required=True, help="same full CSV as build-postcoordinated")
    review.add_argument("--simple-tabulation", type=Path, default=DEFAULT_INPUT, help="only used for the release label")
    review.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR / "postcoord_index_review.html")
    review.add_argument("--rows", choices=["all", "ok", "rejected"], default="all",
        help="which rows to include in the HTML (default: all, so ok/rejected can be compared side by side)")
    return parser.parse_args(argv)


def command_fetch_assets(args: argparse.Namespace) -> int:
    for key in sorted(asset_registry.ASSETS):
        asset_registry.fetch(key, args.assets_dir, force=args.force)
    return 0


def _file_input(role: str, path: Path, **details) -> dict:
    return {"role": role, "path": display_path(path), "sha256": sha256_file(path), "bytes": Path(path).stat().st_size, **details}


def alias_inputs(args, flat, postcoord_index, release, index_entities) -> list[dict]:
    inputs = []
    if flat:
        inputs.append(_file_input(
            "flat-foundation-synonyms-csv", args.flat_synonyms, release=release,
            authority="WHO (content) via local WHO ICD-API search index, not a WHO-published file",
            generator="ciel-scripts/list_flat_foundation_synonyms.py (read-only reference; not imported by this pipeline)",
        ))
    if postcoord_index:
        inputs.append(_file_input(
            "postcoordinated-index-full-csv", args.postcoordinated_csv, release=release,
            authority="WHO (content) via local WHO ICD-API search index, not a WHO-published file",
            generator="ciel-scripts/list_postcoordinated_index_codes.py --full-csv (read-only reference; not imported by this pipeline)",
            include_rejected=args.include_rejected,
        ))
        inputs.append(_file_input(
            "icd-api-search-index", args.index_file, release=release,
            authority="WHO ICD-API search index (ix_*mms*.pbf) copied read-only from a local whoicd/icd-api container; not committed",
            composites_with_entities=len(index_entities),
            entities=sum(len(entities) for entities in index_entities.values()),
        ))
    return inputs


def alias_audit(flat, flat_stats, postcoord_index, postcoord_result) -> dict:
    audit = {
        "name_type": "omitted (null)",
        "policy": (
            "Owner decision: every WHO Foundation title or synonym added here is an untyped name (no name_type key; "
            "OCL stores null, never the string 'None'). They are lexical aliases of Foundation entities, not an asserted "
            "equivalence: flat-code entities are narrower or residual roll-ups of the code (no row has the code's own title)."
        ),
    }
    if flat:
        audit["flat"] = {
            "rows_read": flat.total_read,
            "rows_skipped_without_code_or_name": flat.skipped,
            "duplicate_names_in_csv": flat.duplicate_names,
            "names_added": flat_stats["names_added"],
            "concepts_with_aliases": flat_stats["concepts_with_aliases"],
            "equal_to_fsn": flat_stats["equal_to_fsn"],
            "unknown_codes": flat_stats["unknown_codes"],
            "evidence": flat.evidence_counts,
            "note": "evidence is the generator's heuristic, kept for review; it does not filter or label any name",
        }
    if postcoord_result:
        stats = postcoord_result.alias_stats
        missing = stats["rows_without_index_entities"]
        audit["postcoordinated"] = {
            "rows_read": postcoord_index.total_read,
            "rows_kept": len(postcoord_index.rows),
            "names_added": stats["names_added"],
            "concepts_with_aliases": stats["rows_with_aliases"],
            "equal_to_fsn": stats["equal_to_fsn"],
            "rows_without_index_entities": len(missing),
            "rows_without_index_entities_sample": missing[:20],
            "note": "aliases = every Foundation entity title and synonym the search index attaches to the composite, then the CSV's own synonyms",
        }
    return audit


def command_build(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.is_file():
        print(f"error: Simple Tabulation input not found: {path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    if args.postcoordinated_csv and not args.index_file:
        print("error: --postcoordinated-csv needs --index-file (the aliases of every post-coordinated code come from it)", file=sys.stderr)
        return 1
    if args.index_file and not args.postcoordinated_csv:
        print("error: --index-file only applies together with --postcoordinated-csv", file=sys.stderr)
        return 1
    for label, given in (("flat synonyms CSV", args.flat_synonyms), ("post-coordinated CSV", args.postcoordinated_csv), ("index file", args.index_file)):
        if given and not Path(given).is_file():
            print(f"error: {label} not found: {given}", file=sys.stderr)
            return 1
    tabulation = simple_tabulation.read(path)
    print(f"{tabulation.version_label}: {len(tabulation.rows):,} entities, {len(tabulation.skipped):,} rows skipped")
    flat = flat_synonyms.read(args.flat_synonyms) if args.flat_synonyms else None
    result = build(tabulation, flat.by_code if flat else None)
    lines = result.lines

    postcoord_index = postcoord_result = index_entities = None
    if args.postcoordinated_csv:
        postcoord_index = postcoordinated.read(args.postcoordinated_csv, release=tabulation.release, include_rejected=args.include_rejected)
        index_entities = foundation_index.read_index_entities(args.index_file, tabulation.release)
        known_ids = {row.id for row in tabulation.rows} | {simple_tabulation.ROOT_ID}
        postcoord_result = build_postcoordinated(postcoord_index, known_ids, index_entities)
        collisions = sorted(known_ids & {line["id"] for line in postcoord_result.concept_lines})
        if collisions:
            print(f"error: {len(collisions)} post-coordinated id(s) collide with the base Source, e.g. {collisions[:5]}", file=sys.stderr)
            return 1
        # concepts before the mappings that point at them: OCL imports the lines in order
        lines = lines + postcoord_result.concept_lines + postcoord_result.mapping_lines

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, lines, args.max_part_size)
    bundle = write_bundle(output_dir, lines)

    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    mode = "full-source-load"
    warning = (
        "Test terminology: the bulk-import lines were generated from the Simple Tabulation alone and "
        "nothing was verified against OCL. They create complete concepts (names and extras), so load them "
        "only into an empty WHO/ICD-11-WHO Source; the importer would overwrite an existing concept."
    )
    if flat or postcoord_result:
        warning += (
            " Alias names carry no name_type; they are WHO Foundation titles/synonyms kept as lexical aliases, "
            "not an asserted equivalence (flat-code entities are narrower or residual roll-ups of the code)."
        )
    upload_comment = "pending: not yet rehearsed against a local OCL instance; full-source-load needs an empty Source"
    bundle_archive_info = None
    parts_archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target,
            mode=mode,
            upload_ready=upload_ready_map(False, upload_comment),
            parts=[part.__dict__ for part in parts],
            bundle=bundle.__dict__,
            method=args.zip_method,
            bundle_archive=args.archive_name,
            parts_archive=args.parts_archive_name,
        )
        bundle_archive_info = create_archive(
            output_dir,
            files=[output_dir / bundle.name],
            archive_name=args.archive_name,
            method=args.zip_method,
        )
        parts_archive_info = create_archive(
            output_dir,
            files=[output_dir / part.zip for part in parts],
            manifest=manifest,
            archive_name=args.parts_archive_name,
            method=args.zip_method,
        )
    if LEGACY_ARCHIVE not in {args.archive_name, args.parts_archive_name}:
        (output_dir / LEGACY_ARCHIVE).unlink(missing_ok=True)

    def archive_record(info):
        if info is None:
            return None
        return {
            **{key: value for key, value in info.__dict__.items() if key != "members"},
            "members": [member.__dict__ for member in info.members],
            "ratio": round(info.ratio, 4),
            "sha256": sha256_file(output_dir / info.name),
        }

    reasons: dict[str, int] = {}
    for entry in tabulation.skipped:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    asset = asset_registry.resolve("simple-tabulation")
    sha = sha256_file(path)
    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready_map(False, upload_comment),
        "warning": warning,
        "inputs": [
            {
                "role": "simple-tabulation",
                "path": display_path(path),
                "sha256": sha,
                "bytes": path.stat().st_size,
                "authority": asset.authority,
                "edition": asset.edition,
                "release": tabulation.release,
                "version_label": tabulation.version_label,
                "matches_pinned_asset": sha == asset.sha256,
                "source_url": asset.url,
            }
        ],
        "read": {"entities": len(tabulation.rows), "skipped": dict(sorted(reasons.items()))},
        "build": {
            "lines": len(lines),
            "class_counts": result.class_counts,
            "rooted_without_parent": result.rooted_without_parent,
            "max_part_zip_bytes": args.max_part_size,
        },
        "output": {
            "directory": display_path(output_dir),
            "parts": [part.__dict__ for part in parts],
            "bundle": bundle.__dict__,
            "bundle_archive": archive_record(bundle_archive_info),
            "parts_archive": archive_record(parts_archive_info),
            "versioned": sorted(([bundle_archive_info.name] if bundle_archive_info else []) + ["bulkimport_audit.json"]),
            "not_versioned": [part.name for part in parts]
            + [part.zip for part in parts]
            + [bundle.name]
            + ([parts_archive_info.name] if parts_archive_info else []),
        },
        "projection": {
            "included": [
                "type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired",
                "names", "extras", "parent_concept_urls",
            ],
            "omitted": ["Source record", "mappings", "post-coordinated codes", "descriptions (except the root)"],
        },
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": (
                "The .bundle.zip contains exactly one complete NDJSON file and can be uploaded as one import. "
                "The .parts.zip is a distribution container, not an OCL upload: extract it, then upload each "
                "inner bulkimport_part_NNN.zip in numeric order through the OCL form, reusing one Queue ID. "
                "Each inner part ZIP contains exactly one NDJSON file."
            ),
        },
    }
    audit["build"]["base_concepts_with_foundation_url"] = sum(
        1 for line in result.lines if "Foundation URL" in line.get("extras", {})
    )
    if flat or postcoord_result:
        audit["aliases"] = alias_audit(flat, result.alias_stats, postcoord_index, postcoord_result)
        audit["inputs"].extend(alias_inputs(args, flat, postcoord_index, tabulation.release, index_entities))
    if postcoord_result:
        audit["build"]["postcoordinated_concepts"] = len(postcoord_result.concept_lines)
        audit["build"]["postcoordinated_mappings"] = len(postcoord_result.mapping_lines)
        audit["build"]["postcoordinated_unknown_stems"] = postcoord_result.unknown_stems
        audit["build"]["postcoordinated_foundation_url"] = postcoord_result.foundation_stats
        audit["build"]["postcoordinated_describe_status"] = dict(sorted(Counter(row.describe_status or "unknown" for row in postcoord_index.rows).items()))
        audit["projection"]["omitted"] = ["Source record", "descriptions (except the root)"]
        audit["projection"]["mapping_fields"] = ["type", "owner", "owner_type", "source", "map_type", "from_concept_url", "to_concept_url"]
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready.local: False")
    print(f"lines: {len(lines):,}   classes: {result.class_counts}")
    if flat:
        print(f"flat aliases: {result.alias_stats['names_added']:,} names on {result.alias_stats['concepts_with_aliases']:,} concepts "
              f"({len(result.alias_stats['unknown_codes'])} unknown codes, {result.alias_stats['equal_to_fsn']} equal to the FSN)")
    if postcoord_result:
        stats = postcoord_result.alias_stats
        print(f"post-coordinated: {len(postcoord_result.concept_lines):,} concepts + {len(postcoord_result.mapping_lines):,} mappings; "
              f"{stats['names_added']:,} alias names on {stats['rows_with_aliases']:,} concepts")
    for part in parts:
        print(f"  {part.zip}  {part.lines:,} lines  {part.bytes:,} bytes → {part.zip_bytes:,} bytes zipped  sha256={part.zip_sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    for info in (bundle_archive_info, parts_archive_info):
        if info:
            print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
    return 0


def command_build_production(args: argparse.Namespace) -> int:
    """PRODUCTION profile: base Simple Tabulation load only.

    Structurally excludes the alias and post-coordinated layers: this subcommand takes no
    ``--flat-synonyms``/``--postcoordinated-csv``/``--index-file`` arguments, so it cannot build them
    even by mistake. Those layers depend on decoding the WHO ICD-API's internal protobuf search index
    and inspecting ``/describe`` outcomes (``pipeline/foundation_index.py``, the sibling
    ``ciel-scripts`` capture) — a reverse-engineering risk the owner does not want anywhere near the
    production Source. This profile reads only the published Simple Tabulation file and emits exactly
    the ``WHO``-sourced columns plus this pipeline's documented, disclosed additions (``concept_class``,
    ``Foundation URL``, the synthetic root) — see README § License and compliance.
    """
    path = Path(args.input)
    if not path.is_file():
        print(f"error: Simple Tabulation input not found: {path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    tabulation = simple_tabulation.read(path)
    print(f"{tabulation.version_label}: {len(tabulation.rows):,} entities, {len(tabulation.skipped):,} rows skipped")
    result = build(tabulation)
    lines = result.lines

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, lines, args.max_part_size)
    bundle = write_bundle(output_dir, lines)

    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    mode = "production-base-load"
    warning = (
        "PRODUCTION profile: base Simple Tabulation load ONLY. No aliases and no post-coordinated "
        "layer were built — both require decoding the WHO ICD-API search index / inspecting /describe "
        "behaviour, which this profile deliberately avoids (reverse-engineering risk under the ICD-11 "
        "licence). The staging bundle (output/staging/) is the full build with that additive layer; it "
        "is never uploaded to production. This bundle creates complete concepts (names and extras), so "
        "load it only into an empty WHO/ICD-11-WHO Source; the importer would overwrite an existing concept."
    )
    upload_comment = "pending: not yet rehearsed against a local OCL instance; full-source-load needs an empty Source"
    bundle_archive_info = None
    parts_archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target,
            mode=mode,
            upload_ready=upload_ready_map(False, upload_comment),
            parts=[part.__dict__ for part in parts],
            bundle=bundle.__dict__,
            method=args.zip_method,
            bundle_archive=args.archive_name,
            parts_archive=args.parts_archive_name,
        )
        bundle_archive_info = create_archive(
            output_dir, files=[output_dir / bundle.name], archive_name=args.archive_name, method=args.zip_method,
        )
        parts_archive_info = create_archive(
            output_dir, files=[output_dir / part.zip for part in parts],
            manifest=manifest, archive_name=args.parts_archive_name, method=args.zip_method,
        )

    def archive_record(info):
        if info is None:
            return None
        return {
            **{key: value for key, value in info.__dict__.items() if key != "members"},
            "members": [member.__dict__ for member in info.members],
            "ratio": round(info.ratio, 4),
            "sha256": sha256_file(output_dir / info.name),
        }

    reasons: dict[str, int] = {}
    for entry in tabulation.skipped:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    asset = asset_registry.resolve("simple-tabulation")
    sha = sha256_file(path)
    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "profile": "production",
        "upload_ready": upload_ready_map(False, upload_comment),
        "warning": warning,
        "inputs": [
            {
                "role": "simple-tabulation",
                "path": display_path(path),
                "sha256": sha,
                "bytes": path.stat().st_size,
                "authority": asset.authority,
                "edition": asset.edition,
                "release": tabulation.release,
                "version_label": tabulation.version_label,
                "matches_pinned_asset": sha == asset.sha256,
                "source_url": asset.url,
            }
        ],
        "read": {"entities": len(tabulation.rows), "skipped": dict(sorted(reasons.items()))},
        "build": {
            "lines": len(lines),
            "class_counts": result.class_counts,
            "rooted_without_parent": result.rooted_without_parent,
            "max_part_zip_bytes": args.max_part_size,
        },
        "output": {
            "directory": display_path(output_dir),
            "parts": [part.__dict__ for part in parts],
            "bundle": bundle.__dict__,
            "bundle_archive": archive_record(bundle_archive_info),
            "parts_archive": archive_record(parts_archive_info),
            "versioned": sorted(([bundle_archive_info.name] if bundle_archive_info else []) + ["bulkimport_audit.json"]),
            "not_versioned": [part.name for part in parts]
            + [part.zip for part in parts]
            + [bundle.name]
            + ([parts_archive_info.name] if parts_archive_info else []),
        },
        "projection": {
            "included": [
                "type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired",
                "names", "extras", "parent_concept_urls",
            ],
            "omitted": [
                "Source record", "mappings", "post-coordinated codes", "alias names (Foundation synonyms)",
                "descriptions (except the root)",
            ],
        },
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": (
                "The .bundle.zip contains exactly one complete NDJSON file and can be uploaded as one import. "
                "The .parts.zip is a distribution container, not an OCL upload: extract it, then upload each "
                "inner bulkimport_part_NNN.zip in numeric order through the OCL form, reusing one Queue ID. "
                "Each inner part ZIP contains exactly one NDJSON file."
            ),
        },
    }
    audit["build"]["base_concepts_with_foundation_url"] = sum(
        1 for line in result.lines if "Foundation URL" in line.get("extras", {})
    )
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"profile: production   mode: {mode}   upload_ready.local: False")
    print(f"lines: {len(lines):,}   classes: {result.class_counts}")
    for part in parts:
        print(f"  {part.zip}  {part.lines:,} lines  {part.bytes:,} bytes → {part.zip_bytes:,} bytes zipped  sha256={part.zip_sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    for info in (bundle_archive_info, parts_archive_info):
        if info:
            print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
    return 0


def command_build_postcoordinated(args: argparse.Namespace) -> int:
    tabulation_path = Path(args.simple_tabulation)
    if not tabulation_path.is_file():
        print(f"error: Simple Tabulation input not found: {tabulation_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: post-coordinated index CSV not found: {input_path}", file=sys.stderr)
        return 1

    tabulation = simple_tabulation.read(tabulation_path)
    root_id = simple_tabulation.ROOT_ID
    known_stem_ids = {row.id for row in tabulation.rows}
    known_stem_ids.add(root_id)
    index = postcoordinated.read(input_path, release=tabulation.release, include_rejected=args.include_rejected)
    index_entities = None
    if args.index_file:
        if not Path(args.index_file).is_file():
            print(f"error: index file not found: {args.index_file}", file=sys.stderr)
            return 1
        index_entities = foundation_index.read_index_entities(args.index_file, tabulation.release)
    result = build_postcoordinated(index, known_stem_ids, index_entities)

    collisions = sorted(known_stem_ids & {line["id"] for line in result.concept_lines})
    if collisions:
        print(f"error: {len(collisions)} post-coordinated id(s) collide with the base Source, e.g. {collisions[:5]}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    all_lines = result.concept_lines + result.mapping_lines
    parts = write_parts(output_dir, all_lines, args.max_part_size)
    bundle = write_bundle(output_dir, all_lines)

    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    mode = "incremental-add"
    warning = (
        "Test terminology, additive layer: this bundle ONLY adds new concepts (indexed post-coordinated "
        "codes, concept_class Diagnosis, extras.isPostcoordinated=True) and NARROWER-THAN mappings to "
        "their first stem. It never creates, modifies, or deletes a concept already in the base Simple "
        "Tabulation load, and nothing here was verified against OCL yet."
    )
    bundle_archive_info = None
    parts_archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target, mode=mode,
            upload_ready=upload_ready_map(False, "pending: not yet rehearsed against a local OCL instance"),
            parts=[part.__dict__ for part in parts], bundle=bundle.__dict__, method=args.zip_method,
            bundle_archive=args.archive_name, parts_archive=args.parts_archive_name,
        )
        bundle_archive_info = create_archive(output_dir, files=[output_dir / bundle.name], archive_name=args.archive_name, method=args.zip_method)
        parts_archive_info = create_archive(output_dir, files=[output_dir / part.zip for part in parts], manifest=manifest, archive_name=args.parts_archive_name, method=args.zip_method)

    def archive_record(info):
        if info is None:
            return None
        return {
            **{key: value for key, value in info.__dict__.items() if key != "members"},
            "members": [member.__dict__ for member in info.members],
            "ratio": round(info.ratio, 4),
            "sha256": sha256_file(output_dir / info.name),
        }

    reasons: dict[str, int] = {}
    for entry in index.skipped:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready_map(False, "pending: not yet rehearsed against a local OCL instance"),
        "warning": warning,
        "inputs": [
            {
                "role": "postcoordinated-index-full-csv",
                "path": display_path(input_path),
                "sha256": sha256_file(input_path),
                "bytes": input_path.stat().st_size,
                "authority": "WHO (content) via local WHO ICD-API search index, not a WHO-published file",
                "release": tabulation.release,
                "generator": "ciel-scripts/run_icd_api_postcoord_index_export.sh (read-only reference; not imported by this pipeline)",
                "include_rejected": args.include_rejected,
            },
            {"role": "simple-tabulation-for-stem-ids", "path": display_path(tabulation_path), "release": tabulation.release},
        ],
        "read": {"total_read": index.total_read, "kept": len(index.rows), "skipped": dict(sorted(reasons.items()))},
        "build": {
            "concept_lines": len(result.concept_lines),
            "mapping_lines": len(result.mapping_lines),
            "unknown_stems": result.unknown_stems,
            "foundation_url": result.foundation_stats,
            "describe_status": dict(sorted(Counter(row.describe_status or "unknown" for row in index.rows).items())),
            "max_part_zip_bytes": args.max_part_size,
        },
        "review": {
            "rejected_codes_not_included_by_default": True,
            "note": "describe_status=rejected_by_api rows are excluded unless --include-rejected is passed; "
                    "review them first (entity id + public WHO browser link) before deciding.",
        },
        "output": {
            "directory": display_path(output_dir),
            "parts": [part.__dict__ for part in parts],
            "bundle": bundle.__dict__,
            "bundle_archive": archive_record(bundle_archive_info),
            "parts_archive": archive_record(parts_archive_info),
            "versioned": sorted(([bundle_archive_info.name] if bundle_archive_info else []) + ["bulkimport_audit.json"]),
            "not_versioned": [part.name for part in parts] + [part.zip for part in parts] + [bundle.name]
                + ([parts_archive_info.name] if parts_archive_info else []),
        },
        "projection": {
            "concept_fields": ["type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired", "names", "extras"],
            "mapping_fields": ["type", "owner", "owner_type", "source", "map_type", "from_concept_url", "to_concept_url"],
            "omitted": ["parent_concept_urls (deliberately not set: mapping-only, per owner decision)", "descriptions", "Source record"],
        },
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": (
                "ADDITIVE ONLY: upload into the already-populated WHO/ICD-11-WHO Source, never into an empty "
                "one. The .bundle.zip contains exactly one complete NDJSON file and can be uploaded as one "
                "import. The .parts.zip is a distribution container: extract it, then upload each inner "
                "bulkimport_part_NNN.zip in numeric order through the OCL form, reusing one Queue ID."
            ),
        },
    }
    if index_entities is not None:
        audit["aliases"] = alias_audit(None, None, index, result)
        audit["inputs"].append(_file_input(
            "icd-api-search-index", args.index_file, release=tabulation.release,
            authority="WHO ICD-API search index (ix_*mms*.pbf) copied read-only from a local whoicd/icd-api container; not committed",
            composites_with_entities=len(index_entities),
            entities=sum(len(entities) for entities in index_entities.values()),
        ))
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready.local: False")
    print(f"concepts: {len(result.concept_lines):,}   mappings: {len(result.mapping_lines):,}   unknown stems: {len(result.unknown_stems)}")
    for part in parts:
        print(f"  {part.zip}  {part.lines:,} lines  {part.bytes:,} bytes → {part.zip_bytes:,} bytes zipped  sha256={part.zip_sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    for info in (bundle_archive_info, parts_archive_info):
        if info:
            print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
    if result.unknown_stems:
        print(f"warning: {len(result.unknown_stems)} post-coordinated code(s) skipped: stem not in the base Source, e.g. {result.unknown_stems[:5]}", file=sys.stderr)
    return 0


def command_review(args: argparse.Namespace) -> int:
    tabulation_path = Path(args.simple_tabulation)
    if not tabulation_path.is_file():
        print(f"error: Simple Tabulation input not found: {tabulation_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: post-coordinated index CSV not found: {input_path}", file=sys.stderr)
        return 1

    tabulation = simple_tabulation.read(tabulation_path)
    index_all = postcoordinated.read(input_path, release=tabulation.release, include_rejected=True)
    total_ok = sum(1 for row in index_all.rows if row.describe_status == "ok")
    total_rejected = len(index_all.rows) - total_ok
    total_own_entity = sum(1 for row in index_all.rows if row.foundation_entity_id)
    if args.rows == "ok":
        rows = [row for row in index_all.rows if row.describe_status == "ok"]
    elif args.rows == "rejected":
        rows = [row for row in index_all.rows if row.describe_status != "ok"]
    else:
        rows = index_all.rows
    review.write_review_html(
        args.output, rows, release=tabulation.release, total_indexed=len(index_all.rows),
        total_ok=total_ok, total_rejected=total_rejected, total_own_entity=total_own_entity,
    )
    print(f"rows written: {len(rows):,}   (ok: {total_ok:,}  rejected: {total_rejected:,}  with own entity id: {total_own_entity:,})   output: {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "fetch-assets":
            return command_fetch_assets(args)
        if args.command == "build-postcoordinated":
            return command_build_postcoordinated(args)
        if args.command == "build-production":
            return command_build_production(args)
        if args.command == "review":
            return command_review(args)
        return command_build(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
