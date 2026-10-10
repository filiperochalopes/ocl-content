"""ICD-11 base Source: Simple Tabulation to versioned bulk-import artifacts.

    # fetch the pinned WHO release (verified by SHA-256; never committed)
    python3 terminologies/icd/icd-11/pipeline/cli.py fetch-assets

    # build the parts, the whole bundle, and the versioned archive
    python3 terminologies/icd/icd-11/pipeline/cli.py build

Uploading is manual and stays manual. This CLI makes no network call apart from ``fetch-assets``
(a public, hash-verified download) and never calls an OCL write, import, or upload endpoint.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The pipeline is imported by path (tools/ocl_pipeline_loader.py), never as a top-level ``pipeline``,
# so another terminology's ``pipeline`` package cannot shadow this one in the same process.
_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from ocl_pipeline_loader import load  # noqa: E402

TERMINOLOGY = "icd/icd-11"


def _pipeline(module: str):
    return load(TERMINOLOGY, module)


asset_registry = _pipeline("assets")
simple_tabulation = _pipeline("simple_tabulation")
_bulk = _pipeline("build_bulkimport")
TARGET_OWNER, TARGET_SOURCE, build = _bulk.TARGET_OWNER, _bulk.TARGET_SOURCE, _bulk.build

from ocl_artifacts import (  # noqa: E402
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
DEFAULT_OUTPUT_DIR = TERMINOLOGY_DIR / "output"
DEFAULT_ARCHIVE = "bulkimport_icd11-who.zip"
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

    build_parser = subparsers.add_parser("build", help="write the bulk-import parts, bundle, audit, and archive")
    build_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Simple Tabulation .zip or .txt")
    build_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build_parser.add_argument("--max-part-size", type=parse_size, default=DEFAULT_PART_BYTES, metavar="SIZE")
    build_parser.add_argument("--zip-method", choices=sorted(METHODS), default=DEFAULT_METHOD)
    build_parser.add_argument("--archive-name", default=DEFAULT_ARCHIVE)
    build_parser.add_argument("--no-archive", action="store_true", help="skip the zip (parts and bundle only)")
    return parser.parse_args(argv)


def command_fetch_assets(args: argparse.Namespace) -> int:
    for key in sorted(asset_registry.ASSETS):
        asset_registry.fetch(key, args.assets_dir, force=args.force)
    return 0


def command_build(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.is_file():
        print(f"error: Simple Tabulation input not found: {path}\n       run: cli.py fetch-assets", file=sys.stderr)
        return 1
    tabulation = simple_tabulation.read(path)
    print(f"{tabulation.version_label}: {len(tabulation.rows):,} entities, {len(tabulation.skipped):,} rows skipped")
    result = build(tabulation)

    output_dir = Path(args.output_dir)
    parts = write_parts(output_dir, result.lines, args.max_part_size)
    bundle = write_bundle(output_dir, result.lines)

    target = {"owner": TARGET_OWNER, "source": TARGET_SOURCE, "owner_type": "Organization"}
    mode = "full-source-load"
    warning = (
        "Test terminology: the bulk-import lines were generated from the Simple Tabulation alone and "
        "nothing was verified against OCL. They create complete concepts (names and extras), so load them "
        "only into an empty WHO/ICD-11-WHO Source; the importer would overwrite an existing concept."
    )
    archive_info = None
    if not args.no_archive:
        manifest = build_manifest(
            target=target,
            mode=mode,
            upload_ready=False,
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

    reasons: dict[str, int] = {}
    for entry in tabulation.skipped:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    asset = asset_registry.resolve("simple-tabulation")
    sha = sha256_file(path)
    audit = {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": False,
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
            "lines": len(result.lines),
            "class_counts": result.class_counts,
            "rooted_without_parent": result.rooted_without_parent,
            "max_part_bytes": args.max_part_size,
        },
        "output": {
            "directory": display_path(output_dir),
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
            "versioned": sorted([path.name for path in output_dir.glob("*.zip")] + ["bulkimport_audit.json"]),
            "not_versioned": [part.name for part in parts] + [bundle.name],
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
                "No tool in this repository uploads to OCL. Extract the parts from the archive and upload them "
                "in numeric order through the OCL bulk-import form, reusing one Queue ID."
            ),
        },
    }
    write_json(output_dir / "bulkimport_audit.json", audit)

    print(f"mode: {mode}   upload_ready: False")
    print(f"lines: {len(result.lines):,}   classes: {result.class_counts}")
    for part in parts:
        print(f"  {part.name}  {part.lines:,} lines  {part.bytes:,} bytes  sha256={part.sha256[:12]}…")
    print(f"bundle: {bundle.name}  {bundle.lines:,} lines  {bundle.bytes:,} bytes")
    if archive_info:
        print(f"archive: {archive_info.name}  {archive_info.bytes:,} bytes ({archive_info.method}, ratio {archive_info.ratio:.3f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "fetch-assets":
            return command_fetch_assets(args)
        return command_build(args)
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
