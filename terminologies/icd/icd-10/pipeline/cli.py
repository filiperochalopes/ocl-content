#!/usr/bin/env python3
"""ICD-10 canonical extraction, national-edition name alignment, and versioned bulk-import build.

    # fetch the pinned inputs (verified by SHA-256; never committed)
    python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset all

    # extract the canonical structure from the WHO ClaML and check it against the baseline
    python3 terminologies/icd/icd-10/pipeline/cli.py canonical --who-claml <zip> \
      --out terminologies/icd/icd-10/output/canonical_who_icd10.jsonl \
      --compare "ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv"

    # build the parts, the whole bundle, and the versioned archive
    python3 terminologies/icd/icd-10/pipeline/cli.py build

    # regenerate from live HEAD so the artifacts are safe to upload (read-only GETs)
    OCL_API_TOKEN=… python3 terminologies/icd/icd-10/pipeline/cli.py build --hydrate

Uploading is manual and stays manual. This CLI never calls an OCL write, import, or upload
endpoint: it writes local artifacts — ordered parts, the complete bundle, and one zip holding both
plus a manifest — and an operator uploads the parts through the OCL bulk-import form. ``--hydrate``
performs authenticated GET requests only, and the token is never printed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import assets as asset_registry  # noqa: E402
from pipeline.adapters import atih_claml, datasus_csv, datasus_xml, who_claml  # noqa: E402
from pipeline.align import align  # noqa: E402
from pipeline.build_bulkimport import (  # noqa: E402
    DEFAULT_PART_BYTES,
    TARGET_OWNER,
    TARGET_SOURCE,
    ConceptState,
    PartInfo,
    build,
    write_alignment_csv,
    write_audit_pair,
    write_bundle,
    write_json,
    write_parts,
)
from pipeline.canonical import load_canonical, sha256_file, write_canonical_jsonl  # noqa: E402
from pipeline.compact import (  # noqa: E402
    DEFAULT_METHOD,
    METHODS,
    build_manifest,
    create_archive,
)
from pipeline.hydrate import hydrate  # noqa: E402
from pipeline.model import AdapterResult  # noqa: E402

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
DEFAULT_API_URL = os.environ.get("OCL_API_URL", "https://api.openconceptlab.org")
DEFAULT_ARCHIVE = "bulkimport_icd10-who.zip"
SIZE_RE = re.compile(r"^(\d+)(b|kb|mb|gb)?$", re.IGNORECASE)


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
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    build_parser.add_argument("--skip", action="append", choices=["pt_BR", "fr"], default=[])
    build_parser.add_argument(
        "--exclusions",
        type=Path,
        help="curated CSV of reviewed (code,locale,reason) rows to hold back from the proposal",
    )
    build_parser.add_argument("--hydrate", action="store_true", help="read the targeted concepts from HEAD first")
    build_parser.add_argument("--api-url", default=DEFAULT_API_URL)
    build_parser.add_argument("--token-env", default="OCL_API_TOKEN")
    build_parser.add_argument("--allow-insecure-localhost", action="store_true")
    build_parser.add_argument("--no-archive", action="store_true", help="skip the zip (parts and bundle only)")
    build_parser.add_argument(
        "--dev-audit",
        action="store_true",
        help="also write the pretty-printed before/after pair for diff review (not versioned)",
    )
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_ARCHIVE)

    compact = subparsers.add_parser("compact", help="(re)create the versioned zip from parts already on disk")
    compact.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    compact.add_argument("--archive-name", default=DEFAULT_ARCHIVE)
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
            "path": str(baseline.path),
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
                "path": str(Path(path).resolve()),
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
    hydration_meta = None
    if args.hydrate:
        token = os.environ.get(args.token_env, "")
        if not token:
            print(f"error: --hydrate needs a token in ${args.token_env}", file=sys.stderr)
            return 1
        resources, failures = hydrate(
            args.api_url,
            TARGET_OWNER,
            TARGET_SOURCE,
            codes,
            token,
            allow_insecure_localhost=args.allow_insecure_localhost,
        )
        hydration_meta = {
            "requested": len(codes),
            "retrieved": len(resources),
            "failures": failures,
            "api_url": args.api_url,
        }
        if failures:
            print(f"error: {len(failures)} concepts could not be read from HEAD; no artifacts written", file=sys.stderr)
            for failure in failures[:20]:
                print(f"  {failure['code']}: {failure['error']}", file=sys.stderr)
            return 1
        states = {code: ConceptState.from_export(resource) for code, resource in resources.items()}
        mode = "hydrated-head"
        print(f"hydrated {len(states):,} concepts from {args.api_url}")
    else:
        states = {code: ConceptState.from_canonical(baseline.concepts[code]) for code in codes}
        mode = "offline-baseline"
        print(
            "mode: offline-baseline (draft) — names/descriptions/extras come from the committed baseline; "
            "regenerate with --hydrate before uploading"
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

    generated_at = datetime.now(timezone.utc).isoformat()
    upload_ready = mode == "hydrated-head"
    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    warning = None if upload_ready else (
        "Built from the committed baseline, not from live HEAD. The Concept bulk importer is not a "
        "PATCH: omitting a collection replaces it. Regenerate with --hydrate and re-verify before uploading."
    )
    archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target,
            mode=mode,
            upload_ready=upload_ready,
            generated_at=generated_at,
            parts=[part.__dict__ for part in parts],
            bundle=bundle.__dict__,
            method=args.zip_method,
        )
        archive_info = create_archive(
            output_dir,
            parts=[output_dir / part.name for part in parts],
            bundle=output_dir / bundle.name,
            manifest=manifest,
            archive_name=args.archive_name,
            method=args.zip_method,
        )

    audit = {
        "schema_version": 1,
        "generated_at": generated_at,
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
            "exclusions_file": str(args.exclusions) if args.exclusions else None,
        },
        "build": {
            "status_counts": result.status_counts(),
            "locale_counts": result.locale_counts(),
            "changed_concepts": len(result.lines),
            "max_part_bytes": args.max_part_size,
        },
        "hydration": hydration_meta,
        "output": {
            "directory": str(output_dir.resolve()),
            "parts": [part.__dict__ for part in parts],
            "bundle": bundle.__dict__,
            "archive": (
                {
                    **{key: value for key, value in archive_info.__dict__.items() if key != "members"},
                    "members": [member.__dict__ for member in archive_info.members],
                    "ratio": round(archive_info.ratio, 4),
                    "sha256": sha256_file(output_dir / archive_info.name),
                }
                if archive_info
                else None
            ),
            "versioned": sorted(
                [path.name for path in output_dir.glob("*.zip")] + ["bulkimport_audit.json"]
            ),
            "not_versioned": [part.name for part in parts]
            + [bundle.name, report_path.name]
            + ([dev_audit_info.before, dev_audit_info.after] if dev_audit_info else []),
        },
        "dev_audit": dev_audit_meta,
        "projection": {
            "included": ["type", "id", "concept_class", "names", "descriptions", "extras", "owner", "owner_type", "source"],
            "omitted": ["datatype", "external_id", "retired", "parent_concept_urls", "mappings"],
            "rationale": (
                "OCL preserves omitted scalar values and hierarchy, and an empty mappings payload is a no-op, "
                "while a Concept bulk update replaces an omitted names/descriptions collection with an empty one. "
                "Full names/descriptions/extras are therefore always sent."
            ),
        },
        "upload": {
            "mechanism": "manual",
            "api_upload": False,
            "note": (
                "No tool in this repository uploads to OCL. Extract the parts from the archive and upload them "
                "in numeric order through the OCL bulk-import form, reusing one Queue ID."
            ),
        },
    }
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready: {upload_ready}")
    print(f"changed concepts: {len(result.lines):,}   by locale: {result.locale_counts()}")
    for part in parts:
        print(f"  {part.name}  {part.lines:,} lines  {part.bytes:,} bytes  sha256={part.sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    if archive_info:
        print(
            f"archive: {archive_info.name}  {archive_info.bytes:,} bytes "
            f"({archive_info.method}, ratio {archive_info.ratio:.3f})"
        )
    print(f"audit: {output_dir / 'bulkimport_audit.json'}")
    print(f"alignment report (not versioned): {report_path}")
    if dev_audit_info:
        print(f"dev audit pair (not versioned): {dev_audit_info.before} / {dev_audit_info.after}")
        print("  review the diff by pasting both files into a JSON-aware diff viewer (e.g. diffchecker.com)")
    return 0


def command_compact(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    parts = sorted(output_dir.glob("bulkimport_part_*.ndjson"))
    bundle = output_dir / "bulkimport_bundle.ndjson"
    if not parts or not bundle.is_file():
        print(f"error: no parts/bundle to archive in {output_dir}", file=sys.stderr)
        return 1
    audit_path = output_dir / "bulkimport_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}

    def info(path: Path) -> dict:
        payload = path.read_bytes()
        return PartInfo(
            name=path.name,
            lines=payload.count(b"\n"),
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
        ).__dict__

    manifest = build_manifest(
        target=audit.get("target", {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}),
        mode=audit.get("mode", "unknown"),
        upload_ready=bool(audit.get("upload_ready", False)),
        generated_at=datetime.now(timezone.utc).isoformat(),
        parts=[info(path) for path in parts],
        bundle=info(bundle),
        method=args.zip_method,
    )
    archive_info = create_archive(
        output_dir,
        parts=parts,
        bundle=bundle,
        manifest=manifest,
        archive_name=args.archive_name,
        method=args.zip_method,
    )
    print(
        f"archive: {archive_info.name}  {archive_info.bytes:,} bytes ({archive_info.method}, "
        f"ratio {archive_info.ratio:.3f})  members: {len(archive_info.members)}"
    )
    for member in archive_info.members:
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
