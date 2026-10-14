"""WHO-ATC: BioPortal ATC ontology to versioned bulk-import artifacts.

    # fetch the pinned BioPortal submission (needs BIOPORTAL_API_KEY); the cumulative alterations
    # page is fetched only as an optional cross-check input, never for lifecycle decisions
    python3 terminologies/who/atc/pipeline/cli.py fetch-assets

    # build ordered parts, the full bundle, and the two hand-off ZIPs (offline, no network)
    python3 terminologies/who/atc/pipeline/cli.py build

    # optional, read-only: compare the fresh snapshot against an immutable WHO/WHOATC snapshot;
    # only codes active in that snapshot and absent from the ontology are retirement candidates
    python3 terminologies/who/atc/pipeline/cli.py diff-export --export exports/prod/WHO_WHOATC_HEAD.ndjson

    # optional, network, bounded to 15 requests: spot-check level 1/2 against atcddd.fhi.no itself
    python3 terminologies/who/atc/pipeline/cli.py crosscheck-chapters

    # optional, network, read-only: crawl the public WHOCC Index across levels 1-5 and
    # regenerate the local JSON/HTML comparison against the pinned BioPortal submission
    python3 terminologies/who/atc/pipeline/cli.py crawl-index

``build`` and `diff-export` make no network call and never touch OCL. `fetch-assets`,
`crosscheck-chapters`, and `crawl-index` are the only commands that reach the network, and none
uploads or writes to OCL. Uploading a built artifact stays manual (see `CONTRIBUTING.md`, "Uploading is
manual"); the `.bundle.zip` holds exactly one full-bundle NDJSON file, and the `.parts.zip` is a
distribution wrapper whose inner one-member part ZIPs are uploaded individually, in numeric order,
through the OCL bulk-import form.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from ocl_pipeline_loader import load  # noqa: E402

TERMINOLOGY = "who/atc"


def _pipeline(module: str):
    return load(TERMINOLOGY, module)


asset_registry = _pipeline("assets")
ttl_reader = _pipeline("ttl_reader")
atcddd_crosscheck = _pipeline("atcddd_crosscheck")
atcddd_index = _pipeline("atcddd_index")
align_module = _pipeline("align")
retirements = _pipeline("retirements")
_bulk = _pipeline("build_bulkimport")
TARGET_OWNER, TARGET_SOURCE, build = _bulk.TARGET_OWNER, _bulk.TARGET_SOURCE, _bulk.build

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
from ocl_export import load_concepts  # noqa: E402

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TERMINOLOGY_DIR.parents[2]
ASSETS_DIR = TERMINOLOGY_DIR / "assets"
DEFAULT_TTL_INPUT = asset_registry.ttl_destination(ASSETS_DIR)
DEFAULT_OUTPUT_DIR = TERMINOLOGY_DIR / "output"
DEFAULT_BUNDLE_ARCHIVE = "bulkimport_whoatc.bundle.zip"
DEFAULT_PARTS_ARCHIVE = "bulkimport_whoatc.parts.zip"
SIZE_RE = re.compile(r"^(\d+)(b|kb|mb|gb)?$", re.IGNORECASE)


def parse_size(text: str) -> int:
    match = SIZE_RE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 2mb)")
    unit = (match.group(2) or "b").lower()
    return int(match.group(1)) * {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}[unit]


def display_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch-assets", help="download and verify the pinned BioPortal submission and the alterations page")
    fetch.add_argument("--assets-dir", type=Path, default=ASSETS_DIR)
    fetch.add_argument("--submission", type=int, default=asset_registry.LATEST_SUBMISSION)
    fetch.add_argument("--force", action="store_true", help="re-download even when a verified copy exists")

    build_parser = subparsers.add_parser("build", help="write the bulk-import parts, bundle, audit, and both hand-off ZIPs")
    build_parser.add_argument("--ttl", type=Path, default=DEFAULT_TTL_INPUT, help="BioPortal ATC Turtle export")
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE)
    build_parser.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE)
    build_parser.add_argument("--no-archive", action="store_true")

    diff_parser = subparsers.add_parser("diff-export", help="read-only: classify every code against a WHO/WHOATC export")
    diff_parser.add_argument("--ttl", type=Path, default=DEFAULT_TTL_INPUT)
    diff_parser.add_argument("--export", type=Path, required=True, help="export.json / NDJSON / .zip of WHO/WHOATC")
    diff_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR / "alignment_report.csv")

    retire_parser = subparsers.add_parser(
        "build-retirements",
        help="offline: build an audited retirement-only update from hydrated current OCL concepts",
    )
    retire_parser.add_argument("--ttl", type=Path, default=DEFAULT_TTL_INPUT)
    retire_parser.add_argument(
        "--snapshot", type=Path, required=True,
        help="hydrated candidate Concept NDJSON (not the summary listing; see tools/ocl_concept_hydrate.py)",
    )
    retire_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "retirements")
    retire_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    retire_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)

    subparsers.add_parser("crosscheck-chapters", help="network, 15 requests: spot-check level 1/2 against atcddd.fhi.no")
    crawl_parser = subparsers.add_parser(
        "crawl-index",
        help="network, read-only: crawl WHOCC ATC/DDD Index levels 1-5 and write local comparison evidence",
    )
    crawl_parser.add_argument("--ttl", type=Path, default=DEFAULT_TTL_INPUT, help="BioPortal ATC Turtle export")
    crawl_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    crawl_parser.add_argument("--delay-seconds", type=float, default=0.10, help="pause before scheduling each WHOCC request (default: 0.10)")
    crawl_parser.add_argument("--timeout", type=float, default=30, help="WHOCC request timeout in seconds (default: 30)")
    crawl_parser.add_argument("--workers", type=int, default=6, help="maximum concurrent WHOCC requests (default: 6)")
    return parser.parse_args(argv)


def command_fetch_assets(args: argparse.Namespace) -> int:
    asset_registry.fetch_ttl(args.assets_dir, submission=args.submission, force=args.force)
    asset_registry.fetch_alterations(args.assets_dir, force=args.force)
    return 0


def command_build(args: argparse.Namespace) -> int:
    ttl_path = Path(args.ttl)
    if not ttl_path.is_file():
        print(f"error: ATC Turtle file not found: {ttl_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    ontology = ttl_reader.read(ttl_path)
    print(f"ontology {ontology.version_info} ({ontology.umls_source}): {len(ontology.classes):,} ATC classes, "
          f"{ontology.skipped_semantic_types} UMLS semantic-type classes skipped")

    result = build(ontology)

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, result.lines, args.max_part_size)
    bundle = write_bundle(output_dir, result.lines)

    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    mode = "full-source-load"
    warning = (
        "The bulk-import lines create complete concepts (names, descriptions, extras) and were not "
        "verified against a live OCL export (use 'diff-export' first). Loading them into a Source that "
        "already has concepts would overwrite names/extras on any id that already exists; retired "
        "concepts emitted here were not reconciled against the Source's current retired state."
    )
    bundle_archive_info = None
    parts_archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target, mode=mode, upload_ready=upload_ready_map(False, "pending tasks: not reconciled against a live export (diff-export); retirement and authority decisions open"),
            parts=[part.__dict__ for part in parts], bundle=bundle.__dict__,
            method=args.zip_method, bundle_archive=args.archive_name, parts_archive=args.parts_archive_name,
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

    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready_map(False, "pending tasks: not reconciled against a live export (diff-export); retirement and authority decisions open"),
        "warning": warning,
        "inputs": [
            {
                "role": "atc-ontology",
                "path": display_path(ttl_path),
                "sha256": sha256_file(ttl_path),
                "bytes": ttl_path.stat().st_size,
                "authority": "NCBO BioPortal (UMLS2RDF export of the ATC ontology)",
                "edition": f"owl:versionInfo {ontology.version_info} ({ontology.umls_source})",
                "classes_read": len(ontology.classes),
                "semantic_type_classes_skipped": ontology.skipped_semantic_types,
            },
        ],
        "build": {
            "lines": len(result.lines),
            "class_counts": result.class_counts,
            "max_part_zip_bytes": args.max_part_size,
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
            "included": ["type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired",
                          "names", "descriptions", "extras", "parent_concept_urls"],
            "omitted": ["Source record", "mappings", "DDD and ATC/DDD Guidelines content"],
        },
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": (
                "The .bundle.zip contains exactly one complete NDJSON file and can be uploaded as one "
                "import. The .parts.zip is a distribution container, not an OCL upload: extract it, then "
                "upload each inner bulkimport_part_NNN.zip in numeric order through the OCL form, reusing "
                "one Queue ID."
            ),
        },
    }
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready.local: False")
    print(f"lines: {len(result.lines):,}   classes: {result.class_counts}")
    for part in parts:
        print(f"  {part.zip}  {part.lines:,} lines  {part.bytes:,} bytes -> {part.zip_bytes:,} bytes zipped")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    for info in (bundle_archive_info, parts_archive_info):
        if info:
            print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
    return 0


def command_diff_export(args: argparse.Namespace) -> int:
    ttl_path = Path(args.ttl)
    if not ttl_path.is_file():
        print(f"error: ATC Turtle file not found: {ttl_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    ontology = ttl_reader.read(ttl_path)
    export_concepts = load_concepts(args.export, TARGET_OWNER, TARGET_SOURCE)
    rows = align_module.align(ontology, export_concepts)
    align_module.write_csv(args.output, rows)
    summary = align_module.summarize(rows)
    print(f"export: {display_path(args.export)}  concepts read: {len(export_concepts):,}")
    print(f"alignment report: {display_path(args.output)}")
    for status, count in summary.items():
        print(f"  {status}: {count:,}")
    candidates = summary.get(align_module.STATUS_MISSING_CANDIDATE, 0)
    if candidates:
        print(
            f"\n{candidates} active code(s) are retirement candidates because they are present in the "
            "immutable OCL snapshot and absent from the BioPortal ontology. No atcddd.fhi.no data was "
            "used to derive that decision; review the report before producing an audited retirement update."
        )
    return 0


def command_build_retirements(args: argparse.Namespace) -> int:
    ttl_path = Path(args.ttl)
    if not ttl_path.is_file():
        print(f"error: ATC Turtle file not found: {ttl_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    ontology = ttl_reader.read(ttl_path)
    snapshot_path = Path(args.snapshot)
    snapshot = load_concepts(snapshot_path, TARGET_OWNER, TARGET_SOURCE)
    result = retirements.build(ontology, snapshot)
    if not result.after:
        print("no active snapshot concepts are absent from the ontology; no retirement artifact was written")
        return 0

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, result.after, args.max_part_size)
    bundle = write_bundle(output_dir, result.after)
    bundle_archive = create_archive(
        output_dir, files=[output_dir / bundle.name], archive_name="bulkimport_whoatc_retirements.bundle.zip", method=args.zip_method
    )
    manifest = build_manifest(
        target={"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"},
        mode="retirement-update",
        upload_ready=upload_ready_map(False, "pending tasks: not reconciled against a live export (diff-export); retirement and authority decisions open"),
        parts=[part.__dict__ for part in parts],
        bundle=bundle.__dict__,
        method=args.zip_method,
        bundle_archive=bundle_archive.name,
        parts_archive="bulkimport_whoatc_retirements.parts.zip",
    )
    parts_archive = create_archive(
        output_dir,
        files=[output_dir / part.zip for part in parts],
        manifest=manifest,
        archive_name="bulkimport_whoatc_retirements.parts.zip",
        method=args.zip_method,
    )
    before_path = output_dir / "retirements_before.dev.audit.json"
    after_path = output_dir / "retirements_after.dev.audit.json"
    write_json(before_path, result.before)
    write_json(after_path, result.after)
    parsed_bundle = [json.loads(line) for line in (output_dir / bundle.name).read_text(encoding="utf-8").splitlines() if line]
    if parsed_bundle != result.after:
        raise AssertionError("retirement bundle does not exactly equal the after audit array")

    audit = {
        "schema_version": 1,
        "target": {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"},
        "mode": "retirement-update",
        "upload_ready": upload_ready_map(False, "pending tasks: not reconciled against a live export (diff-export); retirement and authority decisions open"),
        "warning": (
            "The official OCL HEAD export endpoint returned HTTP 204, so candidate discovery used a "
            "paginated GET /concepts/ listing snapshot and full candidate resources were hydrated with "
            "individual GETs. Re-run candidate discovery and hydration immediately before any manual import "
            "to avoid a state race. This artifact contains no mappings."
        ),
        "inputs": [
            {
                "role": "atc-ontology",
                "path": display_path(ttl_path), "sha256": sha256_file(ttl_path), "bytes": ttl_path.stat().st_size,
                "edition": f"owl:versionInfo {ontology.version_info} ({ontology.umls_source})",
            },
            {
                "role": "hydrated-ocl-candidates",
                "path": display_path(snapshot_path), "sha256": sha256_file(snapshot_path),
                "concepts": len(snapshot),
                "snapshot_type": "direct GET concept resources; not a ready OCL Source export",
            },
        ],
        "decision_rule": "active in the OCL snapshot AND absent by exact code from the BioPortal ontology",
        "excluded_evidence": ["atcddd.fhi.no alterations", "label/name similarity", "REPLACED BY mappings"],
        "retirements": {"count": len(result.candidate_ids), "ids": result.candidate_ids, "already_retired_ignored": result.ignored_already_retired},
        "audit_pair": {
            "before": before_path.name, "after": after_path.name,
            "same_ordered_ids": [row["id"] for row in result.before] == [row["id"] for row in result.after],
            "ndjson_equals_after": True,
        },
        "output": {
            "directory": display_path(output_dir), "parts": [part.__dict__ for part in parts], "bundle": bundle.__dict__,
            "bundle_archive": {"name": bundle_archive.name, "sha256": sha256_file(output_dir / bundle_archive.name)},
            "parts_archive": {"name": parts_archive.name, "sha256": sha256_file(output_dir / parts_archive.name)},
        },
        "upload": {
            "mechanism": "manual", "api_upload": False, "update_existing_required": True,
            "note": "If approved after audit review, upload the single-member bundle or the extracted inner parts with Update existing enabled. No mapping resource is present.",
        },
    }
    write_json(output_dir / "retirement_audit.json", audit)
    print(f"retirement candidates: {len(result.candidate_ids):,}   mappings: 0")
    print(f"before/after audit: {display_path(before_path)} / {display_path(after_path)}")
    print(f"bundle: {bundle_archive.name} ({bundle.lines:,} lines; manual import only, Update existing required)")
    return 0


def command_crosscheck_chapters(args: argparse.Namespace) -> int:
    ttl_path = DEFAULT_TTL_INPUT
    if not ttl_path.is_file():
        print(f"error: ATC Turtle file not found: {ttl_path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    ontology = ttl_reader.read(ttl_path)
    by_level: dict[int, set[str]] = {}
    for entry in ontology.classes:
        by_level.setdefault(entry.level, set()).add(entry.code)
    result = atcddd_crosscheck.crosscheck(by_level)
    print(f"atcddd.fhi.no last updated: {result.last_updated}")
    print(f"chapters checked: {', '.join(result.chapters_checked)}")
    print(f"level-2 codes in the ontology but not on atcddd.fhi.no: {result.missing_from_atcddd or 'none'}")
    print(f"level-2 codes on atcddd.fhi.no but not in the ontology: {result.missing_from_ontology or 'none'}")
    output_path = DEFAULT_OUTPUT_DIR / "atcddd_crosscheck.json"
    write_json(output_path, {
        "chapters_checked": result.chapters_checked,
        "atcddd_last_updated": result.last_updated,
        "missing_from_atcddd": result.missing_from_atcddd,
        "missing_from_ontology": result.missing_from_ontology,
        "scope": "level 1 (chapters) and level 2 (groups) only; see README 'Known limits'",
    })
    print(f"report: {display_path(output_path)}")
    return 0


def command_crawl_index(args: argparse.Namespace) -> int:
    ttl_path = Path(args.ttl)
    if not ttl_path.is_file():
        print(f"error: ATC Turtle file not found: {ttl_path}\\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    ontology = ttl_reader.read(ttl_path)
    crawl_result = atcddd_index.crawl(
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        workers=args.workers,
    )
    comparison = atcddd_index.compare(ontology, crawl_result)
    output_dir = Path(args.output_dir)
    payload = atcddd_index.report_payload(
        crawl_result=crawl_result,
        comparison=comparison,
        bioportal_path=Path(display_path(ttl_path)),
        bioportal_sha256=sha256_file(ttl_path),
        bioportal_version=ontology.version_info,
    )
    snapshot = {
        "metadata": {
            "who_source": atcddd_index.INDEX_URL,
            "crawl_scope": "all ATC levels 1-5; hierarchy links for levels 1-4 and authoritative table rows for level 5",
            "pages_requested": crawl_result.pages_requested,
            "request_errors": crawl_result.errors,
            "who_last_updated": crawl_result.last_updated,
            "label_source": "WHOCC public ATC/DDD Index",
        },
        "counts": {"total": len(crawl_result.records), "by_level": crawl_result.counts_by_level},
        "records": [
            {"code": record.code, "title": record.title, "level": record.level, "parent": record.parent}
            for record in crawl_result.records
        ],
    }
    snapshot_path = output_dir / "whoatc_index_snapshot.json"
    audit_json_path = output_dir / "whoatc_bioportal_vs_who_audit.json"
    audit_html_path = output_dir / "whoatc_bioportal_vs_who_audit.html"
    atcddd_index.write_json(snapshot_path, snapshot)
    atcddd_index.write_json(audit_json_path, payload)
    atcddd_index.write_html(audit_html_path, payload)
    print(f"WHOCC Index records: {len(crawl_result.records):,}  by level: {crawl_result.counts_by_level}")
    print(f"WHOCC pages requested: {crawl_result.pages_requested:,}  last updated: {crawl_result.last_updated}")
    print(f"BioPortal ATC records: {len(ontology.classes):,}  by level: {comparison.bioportal_by_level}")
    for status, count in comparison.counts.items():
        print(f"{status}: {count:,}")
    print(f"snapshot: {display_path(snapshot_path)}")
    print(f"audit JSON: {display_path(audit_json_path)}")
    print(f"audit HTML: {display_path(audit_html_path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "fetch-assets":
            return command_fetch_assets(args)
        if args.command == "build":
            return command_build(args)
        if args.command == "diff-export":
            return command_diff_export(args)
        if args.command == "build-retirements":
            return command_build_retirements(args)
        if args.command == "crosscheck-chapters":
            return command_crosscheck_chapters(args)
        if args.command == "crawl-index":
            return command_crawl_index(args)
        raise ValueError(f"unknown command {args.command!r}")
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
