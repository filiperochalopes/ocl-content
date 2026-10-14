#!/usr/bin/env python3
"""ICD-10 canonical extraction, national-edition name alignment, and versioned bulk-import build.

    # fetch the pinned inputs (verified by SHA-256; never committed)
    python3 terminologies/who/icd-10/pipeline/cli.py fetch-assets --asset all

    # extract the canonical structure from the WHO ClaML and check it against the baseline
    python3 terminologies/who/icd-10/pipeline/cli.py canonical --who-claml <zip> \
      --out terminologies/who/icd-10/output/canonical_who_icd10.jsonl \
      --compare "ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv"

    # build ordered parts, a complete bundle, and two upload hand-offs
    python3 terminologies/who/icd-10/pipeline/cli.py build

    # start from a fresh export of the Source so the artifacts are safe to upload (offline)
    python3 terminologies/who/icd-10/pipeline/cli.py build --export <WHO_ICD-10-WHO export.json or .zip>

Uploading is manual and stays manual. This CLI makes no network call at all: it writes local
artifacts — ordered parts and their one-member upload ZIPs, the complete NDJSON bundle, a single-member
`.bundle.zip`, and a `.parts.zip` distribution wrapper containing the inner part ZIPs plus a manifest.
Upload the `.bundle.zip` directly for one full import, or extract `.parts.zip` and upload each inner
part ZIP in numeric order. Never upload the outer `.parts.zip`. `--export` reads a Source export
from disk; there is no token, no API client, and no write, import, or upload endpoint.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

# The pipeline is imported by path (tools/ocl_pipeline_loader.py), never as a top-level ``pipeline``,
# so another terminology's ``pipeline`` package cannot shadow this one in the same process.
_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from ocl_pipeline_loader import load  # noqa: E402

TERMINOLOGY = "who/icd-10"


def _pipeline(module: str):
    return load(TERMINOLOGY, module)


asset_registry = _pipeline("assets")
atih_claml, datasus_csv, datasus_xml, who_claml = (
    _pipeline(f"adapters.{name}") for name in ("atih_claml", "datasus_csv", "datasus_xml", "who_claml")
)
align = _pipeline("align").align
_bulk = _pipeline("build_bulkimport")
DEFAULT_PART_BYTES, TARGET_OWNER, TARGET_SOURCE = _bulk.DEFAULT_PART_BYTES, _bulk.TARGET_OWNER, _bulk.TARGET_SOURCE
ConceptState, PartInfo, build = _bulk.ConceptState, _bulk.PartInfo, _bulk.build
write_alignment_csv, write_audit_pair = _bulk.write_alignment_csv, _bulk.write_audit_pair
write_bundle, write_json, write_parts = _bulk.write_bundle, _bulk.write_json, _bulk.write_parts
_canonical = _pipeline("canonical")
load_canonical, sha256_file, write_canonical_jsonl = (
    _canonical.load_canonical, _canonical.sha256_file, _canonical.write_canonical_jsonl,
)
source_export = _pipeline("export")
AdapterResult = _pipeline("model").AdapterResult

from ocl_artifacts import DEFAULT_METHOD, METHODS, build_manifest, upload_ready_map, create_archive, part_info_from_disk  # noqa: E402

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TERMINOLOGY_DIR.parents[2]
ASSETS_DIR = TERMINOLOGY_DIR / "assets"

DEFAULT_BASELINE = REPO_ROOT / "ICD-10 for OCL" / "Production_Load_ICD-10_10Nov2021.csv"
DEFAULT_DATASUS = ASSETS_DIR / "datasus" / "2008" / "CID10CSV.zip"
DEFAULT_DATASUS_XML = ASSETS_DIR / "datasus" / "2008" / "CID10XML.zip"
DEFAULT_ATIH = (
    REPO_ROOT
    / "ICD-10 for OCL"
    / "cim10fr2024syst_claml_20231215"
    / "cim10fr2024syst_claml_20231215.xml"
)
DEFAULT_WHO_CLAML = ASSETS_DIR / "who" / "icd102019en" / "icd102019en.xml.zip"
DEFAULT_OUTPUT_DIR = TERMINOLOGY_DIR / "output"
DEFAULT_BUNDLE_ARCHIVE = "bulkimport_icd10-who.bundle.zip"
DEFAULT_PARTS_ARCHIVE = "bulkimport_icd10-who.parts.zip"
LEGACY_ARCHIVE = "bulkimport_icd10-who.zip"
SIZE_RE = re.compile(r"^(\d+)(b|kb|mb|gb)?$", re.IGNORECASE)


def display_path(path: Path) -> str:
    """Repo-relative POSIX path for provenance records; a path outside the repo keeps only its name."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def parse_size(text: str) -> int:
    match = SIZE_RE.match(text.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 2mb)")
    value = int(match.group(1))
    unit = (match.group(2) or "b").lower()
    return value * {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}[unit]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch-assets", help="download and verify a pinned input")
    fetch.add_argument("--asset", default="all", help="asset key or 'all' (default: all)")
    fetch.add_argument("--assets-dir", type=Path, default=ASSETS_DIR)
    fetch.add_argument("--force", action="store_true", help="re-download even when a verified copy exists")

    canonical = subparsers.add_parser(
        "canonical",
        help="extract the canonical structure from the WHO ClaML and optionally verify it",
    )
    canonical.add_argument("--who-claml", type=Path, default=DEFAULT_WHO_CLAML)
    canonical.add_argument("--out", type=Path, help="write the extraction as JSONL")
    canonical.add_argument("--compare", type=Path, help="compare against a baseline CSV or JSONL")

    build_parser = subparsers.add_parser("build", help="align translation names and write the artifacts")
    build_parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="canonical CSV or JSONL")
    build_parser.add_argument("--datasus", type=Path, default=DEFAULT_DATASUS, help="CID10CSV.zip or CID10XML.zip")
    build_parser.add_argument("--atih", type=Path, default=DEFAULT_ATIH)
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE",
        help="cap on the COMPRESSED size of each part's upload ZIP (default 2mb)")
    build_parser.add_argument("--skip", action="append", choices=["pt_BR", "fr"], default=[])
    build_parser.add_argument(
        "--exclusions",
        type=Path,
        help="curated CSV of reviewed (code,locale,reason) rows to hold back from the proposal",
    )
    build_parser.add_argument(
        "--export",
        type=Path,
        help="export of WHO/ICD-10-WHO (export.json, NDJSON, or .zip) holding the current concepts; "
        "marks the artifact upload-ready",
    )
    build_parser.add_argument("--no-archive", action="store_true", help="skip both hand-off ZIPs (parts and bundle remain)")
    build_parser.add_argument(
        "--dev-audit",
        action="store_true",
        help="also write the pretty-printed before/after pair for diff review (not versioned)",
    )
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE, help="single-member full-bundle ZIP")
    build_parser.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE, help="distribution ZIP containing each upload-part ZIP")

    compact = subparsers.add_parser("compact", help="(re)create the versioned zip from parts already on disk")
    compact.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    compact.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE, help="single-member full-bundle ZIP")
    compact.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE, help="distribution ZIP containing each upload-part ZIP")
    compact.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    return parser.parse_args(argv)


def command_fetch_assets(args: argparse.Namespace) -> int:
    if args.asset == "all":
        keys = sorted(asset_registry.ASSETS)
    else:
        try:
            keys = [asset_registry.resolve(args.asset).key]
        except KeyError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    for key in keys:
        asset_registry.fetch(key, args.assets_dir, force=args.force)
    return 0


def command_canonical(args: argparse.Namespace) -> int:
    path = Path(args.who_claml)
    if not path.is_file():
        print(
            f"error: WHO ClaML input not found: {path}\n       run: cli.py fetch-assets --asset who-claml",
            file=sys.stderr,
        )
        return 1
    extraction = who_claml.extract(path)
    print(f"WHO ClaML: {extraction.stats}")
    for reason, count in _count_reasons(extraction.skipped).items():
        print(f"  skipped {reason}: {count:,}")
    if args.out:
        write_canonical_jsonl(extraction.concepts, args.out)
        print(f"wrote {args.out} ({len(extraction.concepts):,} concepts)")
    if args.compare:
        baseline = load_canonical(args.compare)
        report = who_claml.verify(extraction, baseline.concepts)
        print(
            f"verify vs {Path(args.compare).name}: ids in both {report['ids_in_both']:,}, "
            f"only in WHO {len(report['ids_only_in_who']):,}, "
            f"only in baseline {len(report['ids_only_in_baseline']):,}, "
            f"name mismatches {len(report['name_mismatches']):,} "
            f"({report['name_mismatches_prefixed_context']:,} prefix-context, "
            f"{report['name_mismatches_other']:,} other), "
            f"class mismatches {len(report['class_mismatches']):,}"
        )
        if report["ids_only_in_baseline"]:
            print(f"  only in baseline (sample): {', '.join(report['ids_only_in_baseline'][:10])}")
        if report["name_mismatches"]:
            print(f"  name mismatch (sample): {report['name_mismatches'][:3]}")
        if report["ids_only_in_who"]:
            derived = {concept.id for concept in extraction.concepts if ": " in concept.name}
            extra = [concept_id for concept_id in report["ids_only_in_who"] if concept_id not in derived]
            print(
                f"  only in WHO: {len(report['ids_only_in_who']) - len(extra):,} modifier-derived (optional "
                f"subdivisions), {len(extra):,} other (sample: {', '.join(extra[:10])})"
            )
    return 0


def _datasus_adapter(path: Path) -> Callable[[Path], AdapterResult]:
    """Pick the DATASUS reader from the input itself: CSV tables or the DATASUS XML."""
    path = Path(path)
    names = datasus_csv.archive_member_names(path)
    if path.is_dir() or any(name.startswith("CID-10-") for name in names):
        return datasus_csv.candidates
    if "CID10.xml" in names or path.name.lower().endswith(".xml"):
        return datasus_xml.candidates
    raise ValueError(
        f"{path}: unrecognized DATASUS input; expected CID10CSV.zip, CID10XML.zip, or a directory of CSV tables"
    )


def _adapter_inputs(args: argparse.Namespace) -> list[tuple[str, Path, Callable[[Path], AdapterResult]]]:
    inputs: list[tuple[str, Path, Callable[[Path], AdapterResult]]] = []
    if "pt_BR" not in args.skip:
        inputs.append(("pt_BR", args.datasus, _datasus_adapter(args.datasus)))
    if "fr" not in args.skip:
        inputs.append(("fr", args.atih, atih_claml.candidates))
    return inputs


def command_build(args: argparse.Namespace) -> int:
    baseline = load_canonical(args.baseline)
    print(f"canonical baseline: {len(baseline)} concepts {baseline.class_counts} sha256={baseline.sha256[:12]}…")

    results = []
    inputs_meta = [
        {
            "role": "canonical-baseline",
            "path": display_path(baseline.path),
            "sha256": baseline.sha256,
            "bytes": baseline.path.stat().st_size,
        }
    ]
    for locale, path, adapter in _adapter_inputs(args):
        if not Path(path).exists():
            hint = (
                "run: cli.py fetch-assets --asset datasus-csv (or datasus-xml)"
                if locale == "pt_BR"
                else "tracked legacy asset is missing"
            )
            print(f"error: {locale} input not found: {path}\n       {hint}", file=sys.stderr)
            return 1
        result = adapter(Path(path))
        results.append(result)
        print(
            f"{result.authority} ({result.locale}): {len(result.candidates):,} candidates, "
            f"{len(result.skipped):,} skipped {_count_reasons(result.skipped) or ''}"
        )
        inputs_meta.append(
            {
                "role": f"translation-{result.locale}",
                "path": display_path(Path(path)),
                "sha256": sha256_file(Path(path)) if Path(path).is_file() else "",
                "bytes": Path(path).stat().st_size if Path(path).is_file() else 0,
                "authority": result.authority,
                "edition": result.edition,
            }
        )

    alignment = align(results, baseline, load_exclusions(args.exclusions))
    print(f"alignment: {alignment.counts()}")

    grouped = alignment.by_code()
    codes = sorted(grouped)
    export_meta = None
    if args.export:
        export_path = Path(args.export)
        found, missing = source_export.select(
            source_export.load_concepts(export_path, TARGET_OWNER, TARGET_SOURCE), codes
        )
        export_meta = {
            "path": display_path(export_path),
            "sha256": sha256_file(export_path),
            "bytes": export_path.stat().st_size,
            "requested": len(codes),
            "found": len(found),
            "missing": missing,
        }
        if missing:
            print(f"error: {len(missing)} concepts are not in the export; no artifacts written", file=sys.stderr)
            for entry in missing[:20]:
                print(f"  {entry['code']}: {entry['error']}", file=sys.stderr)
            return 1
        states = {code: ConceptState.from_export(resource) for code, resource in found.items()}
        mode = "source-export"
        print(f"read {len(states):,} concepts from the export {export_path.name}")
    else:
        states = {code: ConceptState.from_canonical(baseline.concepts[code]) for code in codes}
        mode = "offline-baseline"
        print(
            "mode: offline-baseline (draft) — names/descriptions/extras come from the committed baseline; "
            "regenerate with --export before uploading"
        )

    result = build(alignment, states)
    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, result.lines, args.max_part_size)
    bundle = write_bundle(output_dir, result.lines)
    report_path = output_dir / "alignment_report.csv"
    write_alignment_csv(report_path, alignment)

    dev_audit_meta = None
    dev_audit_info = None
    if args.dev_audit:
        dev_audit_info = write_audit_pair(output_dir, result.before, result.after)
        dev_audit_meta = {
            "reason": "development/review aid: paste both files into a JSON-aware diff viewer",
            "before": dev_audit_info.before,
            "after": dev_audit_info.after,
            "concepts": dev_audit_info.concepts,
            "versioned": False,
        }

    ready = mode == "source-export"
    upload_ready = upload_ready_map(ready, "ready for local import: built from a Source export of the local instance" if ready else "pending tasks: built from the committed baseline, not from an export")
    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    warning = None if ready else (
        "Built from the committed baseline, not from a Source export. The Concept bulk importer is not a "
        "PATCH: omitting a collection replaces it. Regenerate with --export and re-verify before uploading."
    )
    bundle_archive_info = None
    parts_archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target,
            mode=mode,
            upload_ready=upload_ready,
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

    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready,
        "warning": warning,
        "inputs": inputs_meta,
        "adapters": [
            {
                "authority": r.authority,
                "locale": r.locale,
                "edition": r.edition,
                "candidates": len(r.candidates),
                "skipped": _count_reasons(r.skipped),
                "stats": r.stats,
            }
            for r in results
        ],
        "alignment": {
            "counts": alignment.counts(),
            "accepted_concepts": len(codes),
            "report": report_path.name,
            "exclusions_file": display_path(args.exclusions) if args.exclusions else None,
        },
        "build": {
            "status_counts": result.status_counts(),
            "locale_counts": result.locale_counts(),
            "changed_concepts": len(result.lines),
            "max_part_zip_bytes": args.max_part_size,
        },
        "export": export_meta,
        "output": {
            "directory": display_path(output_dir),
            "parts": [part.__dict__ for part in parts],
            "bundle": bundle.__dict__,
            "bundle_archive": archive_record(bundle_archive_info),
            "parts_archive": archive_record(parts_archive_info),
            "versioned": sorted(([bundle_archive_info.name] if bundle_archive_info else []) + ["bulkimport_audit.json"]),
            "not_versioned": [part.name for part in parts]
            + [part.zip for part in parts]
            + [bundle.name, report_path.name]
            + ([parts_archive_info.name] if parts_archive_info else [])
            + ([dev_audit_info.before, dev_audit_info.after] if dev_audit_info else []),
        },
        "dev_audit": dev_audit_meta,
        "projection": {
            "included": ["type", "id", "concept_class", "names", "descriptions", "extras", "owner", "owner_type", "source"],
            "omitted": ["datatype", "external_id", "retired", "parent_concept_urls", "mappings"],
            "name_fields_omitted": ["external_id"],
            "rationale": (
                "OCL preserves omitted scalar values and hierarchy, and an empty mappings payload is a no-op, "
                "while a Concept bulk update replaces an omitted names/descriptions collection with an empty one. "
                "Full names/descriptions/extras are therefore always sent. Name and description external_id are "
                "not sent: it is a multi-source provenance field with no use here, and an OCL export serializes a "
                "null value as the literal string \"None\"."
            ),
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
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready.local: {upload_ready['local']['status']}")
    print(f"changed concepts: {len(result.lines):,}   by locale: {result.locale_counts()}")
    for part in parts:
        print(f"  {part.zip}  {part.lines:,} lines  {part.bytes:,} bytes → {part.zip_bytes:,} bytes zipped  sha256={part.zip_sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    for info in (bundle_archive_info, parts_archive_info):
        if info:
            print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
    print(f"audit: {output_dir / 'bulkimport_audit.json'}")
    print(f"alignment report (not versioned): {report_path}")
    if dev_audit_info:
        print(f"dev audit pair (not versioned): {dev_audit_info.before} / {dev_audit_info.after}")
        print("  review the diff by pasting both files into a JSON-aware diff viewer (e.g. diffchecker.com)")
    return 0


def command_compact(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    parts = [part_info_from_disk(path) for path in sorted(output_dir.glob("bulkimport_part_*.ndjson"))]
    bundle = output_dir / "bulkimport_bundle.ndjson"
    if not parts or not bundle.is_file():
        print(f"error: no parts/bundle to archive in {output_dir}", file=sys.stderr)
        return 1
    audit_path = output_dir / "bulkimport_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
    manifest = build_manifest(
        target=audit.get("target", {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}),
        mode=audit.get("mode", "unknown"),
        upload_ready=audit.get("upload_ready") if isinstance(audit.get("upload_ready"), dict) else upload_ready_map(False, "pending tasks: legacy audit without per-environment state"),
        parts=[part.__dict__ for part in parts],
        bundle=part_info_from_disk(bundle).__dict__,
        method=args.zip_method,
        bundle_archive=args.archive_name,
        parts_archive=args.parts_archive_name,
    )
    bundle_archive_info = create_archive(
        output_dir,
        files=[bundle],
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
    for info in (bundle_archive_info, parts_archive_info):
        print(f"archive: {info.name}  {info.bytes:,} bytes ({info.method}, ratio {info.ratio:.3f})")
        for member in info.members:
            print(f"  {member.name}  {member.bytes:,} → {member.compressed_bytes:,} bytes")
    return 0


def _count_reasons(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["reason"]] = counts.get(entry["reason"], 0) + 1
    return dict(sorted(counts.items()))


def load_exclusions(path: Path | None) -> dict[tuple[str, str], str]:
    """Read the curated exclusion CSV: ``code,locale,reason`` with a header row."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"exclusions file not found: {path}")

    excluded: dict[tuple[str, str], str] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"code", "locale", "reason"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected columns code,locale,reason")
        for row_number, row in enumerate(reader, start=2):
            code = (row.get("code") or "").strip()
            locale = (row.get("locale") or "").strip()
            if not code or not locale:
                raise ValueError(f"{path} line {row_number}: blank code or locale")
            excluded[(code, locale)] = (row.get("reason") or "").strip()
    return excluded


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "fetch-assets":
            return command_fetch_assets(args)
        if args.command == "canonical":
            return command_canonical(args)
        if args.command == "compact":
            return command_compact(args)
        return command_build(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
