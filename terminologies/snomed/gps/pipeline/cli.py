"""SNOMED GPS 2026-01 to versioned OCL bulk-import artifacts.

    # verify the ZIP manually obtained from SNOMED International's form/email workflow
    uv run python terminologies/snomed/gps/pipeline/cli.py verify-asset

    # create the full 429,674-concept flat GPS artifact; no network call
    uv run python terminologies/snomed/gps/pipeline/cli.py build

The build is local and deterministic. It never calls OCL and never uploads anything. The generated
artifact refreshes `SNOMED-International/SNOMED-GPS`: all 378,553 active January-2026 GPS concepts
and all 51,121 historic inactive concepts in the official package. Manual OCL import remains the
only upload path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from ocl_pipeline_loader import load  # noqa: E402
from ocl_artifacts import (  # noqa: E402
    upload_ready_map,
    DEFAULT_METHOD, DEFAULT_PART_BYTES, METHODS, build_manifest, create_archive, sha256_file,
    write_bundle, write_json, write_parts,
)

TERMINOLOGY = "snomed/gps"


def _pipeline(module: str):
    return load(TERMINOLOGY, module)


assets = _pipeline("assets")
gps_release = _pipeline("gps_release")
bulk = _pipeline("build_bulkimport")

TERMINOLOGY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = TERMINOLOGY_DIR.parents[2]
ASSETS_DIR = TERMINOLOGY_DIR / "assets"
DEFAULT_INPUT = assets.default_path(ASSETS_DIR)
DEFAULT_OUTPUT_DIR = TERMINOLOGY_DIR / "output"
DEFAULT_BUNDLE_ARCHIVE = "bulkimport_snomed-gps.bundle.zip"
DEFAULT_PARTS_ARCHIVE = "bulkimport_snomed-gps.parts.zip"


def parse_size(text: str) -> int:
    suffixes = {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}
    text = text.strip().lower()
    for suffix, multiplier in suffixes.items():
        if text.endswith(suffix) and text[:-len(suffix)].isdigit():
            return int(text[:-len(suffix)]) * multiplier
    if text.isdigit():
        return int(text)
    raise argparse.ArgumentTypeError(f"invalid size: {text!r} (use e.g. 2mb)")


def display_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-asset", help="verify the manually acquired GPS ZIP against its pinned SHA-256")
    verify.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    build_parser = subparsers.add_parser("build", help="write parts, bundle, audit, and both hand-off ZIPs")
    build_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_BUNDLE_ARCHIVE)
    build_parser.add_argument("--parts-archive-name", default=DEFAULT_PARTS_ARCHIVE)
    build_parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def command_verify_asset(args: argparse.Namespace) -> int:
    assets.verify_local(args.input)
    print(f"ok {args.input} (sha256 verified)")
    return 0


def command_build(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        print(f"error: GPS input not found: {source}\n       obtain it through https://www.snomed.org/gps and place it at {DEFAULT_INPUT}", file=sys.stderr)
        return 1
    assets.verify_local(source)
    release = gps_release.read(source)
    result = bulk.build(release)
    print(f"GPS {release.release_date}: {len(release.concepts):,} concepts ({result.active:,} active, {result.retired:,} inactive)")

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, result.lines, args.max_part_size)
    bundle = write_bundle(output_dir, result.lines)
    bundle_archive = parts_archive = None
    target = {"owner": bulk.TARGET_OWNER, "source": bulk.TARGET_SOURCE, "owner_type": bulk.OWNER_TYPE}
    if not args.no_archive:
        manifest = build_manifest(
            target=target, mode="full-source-refresh", upload_ready=upload_ready_map(False, "pending tasks: full-source-refresh expands the 29,577-concept Source to the complete GPS scope; needs fresh snapshot and local rehearsal"), parts=[part.__dict__ for part in parts],
            bundle=bundle.__dict__, method=args.zip_method, bundle_archive=args.archive_name,
            parts_archive=args.parts_archive_name,
        )
        bundle_archive = create_archive(output_dir, files=[output_dir / bundle.name], archive_name=args.archive_name, method=args.zip_method)
        parts_archive = create_archive(
            output_dir, files=[output_dir / part.zip for part in parts], manifest=manifest,
            archive_name=args.parts_archive_name, method=args.zip_method,
        )

    def archive_record(info):
        if info is None:
            return None
        return {"name": info.name, "bytes": info.bytes, "method": info.method, "ratio": round(info.ratio, 4),
                "sha256": sha256_file(output_dir / info.name), "members": [member.__dict__ for member in info.members]}

    audit = {
        "schema_version": 1,
        "target": target,
        "mode": "full-source-refresh",
        "upload_ready": upload_ready_map(False, "pending tasks: full-source-refresh expands the 29,577-concept Source to the complete GPS scope; needs fresh snapshot and local rehearsal"),
        "warning": (
            "This refresh expands the existing 29,577-concept OCL Source to the complete January 2026 GPS "
            "scope (all active concepts plus all concepts inactive since 2012). Before manual import, take a "
            "fresh OCL snapshot and perform a local rehearsal; the importer replaces collection fields."
        ),
        "inputs": [{
            "role": "official-gps-release", "path": display_path(source), "sha256": sha256_file(source),
            "bytes": source.stat().st_size, "authority": assets.GPS_2026_01.authority,
            "edition": assets.GPS_2026_01.edition, "license": "CC BY-ND 4.0",
            "release_date": release.release_date, "member": release.member,
        }],
        "read": {"concepts": len(release.concepts), "active": result.active, "inactive": result.retired},
        "projection": {
            "included": ["type", "id", "owner", "owner_type", "source", "concept_class", "datatype", "retired", "names"],
            "omitted": ["hierarchy", "mappings", "descriptions", "extras", "translations", "SNOMED relationships/definitions"],
            "concept_class_policy": "trailing semantic tag parsed from each source FSN",
            "name_policy": "FSN as non-preferred Fully-Specified; US Preferred Term as preferred untyped name (name_type omitted)",
        },
        "output": {
            "directory": display_path(output_dir), "parts": [part.__dict__ for part in parts], "bundle": bundle.__dict__,
            "bundle_archive": archive_record(bundle_archive), "parts_archive": archive_record(parts_archive),
            "versioned": sorted(([bundle_archive.name] if bundle_archive else []) + ["bulkimport_audit.json"]),
        },
        "upload": {
            "mechanism": "manual", "api_upload": False, "update_existing_required": True,
            "note": "Import through the OCL form with Update existing enabled. The .parts.zip is a distribution wrapper: extract and upload only inner part ZIPs in numeric order with one Queue ID.",
        },
    }
    write_json(output_dir / "bulkimport_audit.json", audit)
    print(f"mode: full-source-refresh   upload_ready.local: False")
    print(f"lines: {len(result.lines):,}   active: {result.active:,}   inactive/retired: {result.retired:,}")
    print(f"parts: {len(parts):,}   bundle: {bundle.name} ({bundle.bytes:,} bytes)")
    if bundle_archive:
        print(f"archive: {bundle_archive.name} ({bundle_archive.bytes:,} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "verify-asset":
            return command_verify_asset(args)
        return command_build(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
