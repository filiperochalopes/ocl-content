#!/usr/bin/env python3
"""Hydrate selected existing OCL concepts into an immutable NDJSON snapshot (GET-only).

Use after an exact ID-set comparison when a full OCL Source export is unavailable. The listing
snapshot identifies candidate IDs, but it does not contain full names/descriptions/extras. This tool
reads a CSV column of IDs and GETs each selected concept individually, preserving the complete
current resource needed to construct a non-destructive audited update.

    uv run python tools/ocl_concept_hydrate.py --env-file .env.production \
      --owner WHO --source WHOATC \
      --ids-csv terminologies/who/atc/output/alignment_report.csv \
      --match-column status --match-value missing-from-ontology-retire-candidate \
      --out exports/prod/WHO_WHOATC_retire_candidates.ndjson

It issues GET requests only, refuses an existing output path, validates that every returned resource
belongs to the requested owner/source, and writes a provenance sidecar. It never imports, uploads,
PATCHes, POSTs, or generates an OCL export.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocl_env  # noqa: E402
import ocl_http  # noqa: E402


def concept_url(origin: str, owner_type: str, owner: str, source: str, concept_id: str) -> str:
    for label, value in (("owner", owner), ("source", source), ("concept id", concept_id)):
        if not ocl_http.OCL_IDENTIFIER_RE.fullmatch(value or ""):
            raise ocl_http.OclHttpError(f"{label} must use OCL identifier characters: {value!r}")
    if owner_type not in ("orgs", "users"):
        raise ocl_http.OclHttpError("owner type must be orgs or users")
    return f"{origin}/{owner_type}/{quote(owner, safe='')}/sources/{quote(source, safe='')}/concepts/{quote(concept_id, safe='')}/"


def selected_ids(path: Path, id_column: str, match_column: str | None, match_value: str | None) -> list[str]:
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or id_column not in reader.fieldnames:
            raise ValueError(f"{path}: CSV has no {id_column!r} column (columns: {reader.fieldnames})")
        if match_column and match_column not in reader.fieldnames:
            raise ValueError(f"{path}: CSV has no {match_column!r} column (columns: {reader.fieldnames})")
        ids = [
            row[id_column].strip()
            for row in reader
            if row.get(id_column, "").strip() and (not match_column or row.get(match_column) == match_value)
        ]
    if not ids:
        raise ValueError(f"{path}: no IDs matched the requested selector")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: selected IDs are not unique")
    return ids


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = ocl_env.bootstrap(argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--owner-type", choices=("orgs", "users"), default="orgs")
    parser.add_argument("--ids-csv", type=Path, required=True)
    parser.add_argument("--id-column", default="code")
    parser.add_argument("--match-column")
    parser.add_argument("--match-value")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--api-url", default=os.getenv("OCL_API_URL", ocl_http.DEFAULT_API_URL))
    parser.add_argument("--token", default=os.getenv("OCL_API_TOKEN"), help="default: OCL_API_TOKEN")
    parser.add_argument("--allow-custom-api-url", action="store_true")
    parser.add_argument("--allow-insecure-localhost", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.match_column) != bool(args.match_value):
        parser.error("--match-column and --match-value must be supplied together")
    args.env = env
    return args


def hydrate(*, origin: str, owner_type: str, owner: str, source: str, token: str | None, ids: list[str], out: Path) -> dict:
    out = Path(out)
    if out.exists():
        raise ocl_http.OclHttpError(f"refusing to overwrite an existing file: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".part")
    digest = hashlib.sha256()
    try:
        with partial.open("x", encoding="utf-8") as stream:
            for position, concept_id in enumerate(ids, start=1):
                resource = ocl_http.get_json(concept_url(origin, owner_type, owner, source, concept_id), token)
                if resource.get("id") != concept_id:
                    raise ocl_http.OclHttpError(f"GET returned id {resource.get('id')!r}, expected {concept_id!r}")
                for key, expected in (("owner", owner), ("source", source)):
                    if resource.get(key) != expected:
                        raise ocl_http.OclHttpError(
                            f"GET {concept_id!r} returned {key} {resource.get(key)!r}, expected {expected!r}"
                        )
                line = json.dumps(resource, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                stream.write(line)
                digest.update(line.encode("utf-8"))
                if position % 25 == 0 or position == len(ids):
                    print(f"hydrated {position:,}/{len(ids):,}")
        partial.replace(out)
    finally:
        partial.unlink(missing_ok=True)
    return {"concepts": len(ids), "bytes": out.stat().st_size, "sha256": digest.hexdigest()}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        origin = ocl_http.validate_api_url(
            args.api_url,
            allow_insecure_localhost=args.allow_insecure_localhost,
            allow_custom_api_url=args.allow_custom_api_url,
        )
        ids = selected_ids(args.ids_csv, args.id_column, args.match_column, args.match_value)
        print(ocl_env.describe_target(origin, args.token, args.env))
        result = hydrate(
            origin=origin, owner_type=args.owner_type, owner=args.owner, source=args.source,
            token=args.token, ids=ids, out=args.out,
        )
        sidecar = args.out.with_name(args.out.name + ".provenance.json")
        sidecar.write_text(json.dumps({
            "snapshot_type": "OCL hydrated concept resources (not a Source export)",
            "api_origin": origin,
            "owner_type": args.owner_type,
            "owner": args.owner,
            "source": args.source,
            "version_requested": "HEAD",
            "selector": {
                "csv": args.ids_csv.name,
                "id_column": args.id_column,
                "match_column": args.match_column,
                "match_value": args.match_value,
            },
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "token_sent": bool(args.token),
            **result,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"saved {args.out} ({result['concepts']:,} concepts, sha256 {result['sha256']})")
        print(f"provenance: {sidecar}")
        return 0
    except (ocl_http.OclHttpError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
