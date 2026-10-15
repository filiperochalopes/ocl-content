"""Offline LOINC translation audit CLI; all commands are read-only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[4] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ocl_pipeline_loader import load  # noqa: E402

audit = load("regenstrief/loinc", "audit")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    ptbr = subparsers.add_parser("audit-ptbr", help="compare official ptBR11 names with one OCL Source export")
    ptbr.add_argument("--release", type=Path, required=True, help="official LOINC release ZIP")
    ptbr.add_argument("--export", type=Path, required=True, help="OCL version export ZIP, downloaded read-only")
    ptbr.add_argument("--version", required=True, help="release and OCL version being compared, e.g. 2.82")
    ptbr.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command != "audit-ptbr":
        raise ValueError(f"unknown command: {args.command}")
    summary = audit.run_audit(args.release, args.export, args.output_dir, args.version)
    print(f"OCL: {summary['ocl_export']['owner']}/{summary['ocl_export']['source']}/{summary['ocl_export']['version']}")
    print(f"LOINC release: {summary['release']['declared_version']} ({summary['counts']['release_rows']:,} pt-BR rows)")
    print(f"Concept comparison: {summary['counts']['concepts']}")
    for field, counts in summary["counts"]["fields"].items():
        print(f"{field}: {counts}")
    print(f"summary: {Path(args.output_dir) / summary['outputs']['summary']}")
    print(f"details: {Path(args.output_dir) / summary['outputs']['details']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
