#!/usr/bin/env python3
"""Download an immutable, read-only list snapshot of the current concepts in an OCL Source.

Use this **only when the server has no ready Source export** (the normal
``tools/ocl_export_download.py`` route answered HTTP 204). It never asks OCL to generate an export,
and makes only paginated ``GET /concepts/`` calls. The output is an NDJSON *listing snapshot*, not an
OCL Source export: each resource contains the current concept summary returned by the list endpoint
(id, owner, source, retired state, display name, class, datatype, etc.), but not the full names,
descriptions, extras, or mappings. It is sufficient for exact code/lifecycle set comparison; it is
not sufficient to build a content-changing update. Any later retirement proposal must hydrate the
candidate concepts individually and preserve their full current content.

    uv run python tools/ocl_concept_snapshot_download.py --env-file .env.production \
        --owner WHO --source WHOATC --out exports/prod/WHO_WHOATC_HEAD.listing.ndjson

The script refuses to overwrite a file, records pagination metadata and SHA-256 in an adjacent
``.provenance.json`` sidecar, and never prints the token. It exits 0 only after every retrieved page
has been written atomically.
"""

from __future__ import annotations

import argparse
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

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTS_DIR = REPO_ROOT / "exports"
OWNER_TYPES = ("orgs", "users")


def concepts_url(origin: str, owner_type: str, owner: str, source: str, page: int, page_size: int) -> str:
    for label, value in (("owner", owner), ("source", source)):
        if not ocl_http.OCL_IDENTIFIER_RE.fullmatch(value or ""):
            raise ocl_http.OclHttpError(f"{label} must use OCL identifier characters: {value!r}")
    if owner_type not in OWNER_TYPES:
        raise ocl_http.OclHttpError(f"owner type must be one of {OWNER_TYPES}")
    return (
        f"{origin}/{owner_type}/{quote(owner, safe='')}/sources/{quote(source, safe='')}/concepts/"
        f"?limit={page_size}&page={page}"
    )


def default_output(origin: str, owner: str, source: str) -> Path:
    host = origin.split("://", 1)[-1].replace(":", "_")
    return EXPORTS_DIR / host / f"{owner}_{source}_HEAD.listing.ndjson"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = ocl_env.bootstrap(argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--owner-type", choices=OWNER_TYPES, default="orgs")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--page-size", type=int, default=1000, help="OCL list page size (default 1000)")
    parser.add_argument("--env-file", type=Path, help="env file with OCL_API_URL / OCL_API_TOKEN (default: .env)")
    parser.add_argument("--api-url", default=os.getenv("OCL_API_URL", ocl_http.DEFAULT_API_URL))
    parser.add_argument("--token", default=os.getenv("OCL_API_TOKEN"), help="default: OCL_API_TOKEN")
    parser.add_argument("--allow-custom-api-url", action="store_true", help="allow an https origin other than production")
    parser.add_argument("--allow-insecure-localhost", action="store_true", help="allow http for localhost and *.localhost")
    args = parser.parse_args(argv)
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size must be in 1..1000")
    args.env = env
    return args


def download_listing(
    *, origin: str, owner_type: str, owner: str, source: str, token: str | None, destination: Path, page_size: int
) -> dict:
    destination = Path(destination)
    if destination.exists():
        raise ocl_http.OclHttpError(f"refusing to overwrite an existing file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    seen: set[str] = set()
    pages = 0
    total = 0
    try:
        with partial.open("x", encoding="utf-8") as stream:
            for page in range(1, 100_001):  # defensive guard against a server repeating pages forever
                url = concepts_url(origin, owner_type, owner, source, page, page_size)
                rows = ocl_http.get_json(url, token)
                if not isinstance(rows, list):
                    raise ocl_http.OclHttpError(f"GET {url} returned a JSON {type(rows).__name__}, expected a list")
                pages += 1
                if not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        raise ocl_http.OclHttpError(f"GET {url} returned a non-object list member")
                    concept_id = str(row.get("id") or "")
                    if not concept_id:
                        raise ocl_http.OclHttpError(f"GET {url} returned a concept summary with no id")
                    if concept_id in seen:
                        raise ocl_http.OclHttpError(
                            f"GET {url} repeated concept {concept_id!r}; refusing a non-immutable snapshot"
                        )
                    seen.add(concept_id)
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    encoded = line.encode("utf-8")
                    stream.write(line)
                    digest.update(encoded)
                    total += 1
                print(f"page {page}: {len(rows):,} concepts ({total:,} total)")
                if len(rows) < page_size:
                    break
            else:
                raise ocl_http.OclHttpError("refusing more than 100,000 pages; pagination did not terminate")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return {"pages": pages, "concepts": total, "sha256": digest.hexdigest(), "bytes": destination.stat().st_size}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        origin = ocl_http.validate_api_url(
            args.api_url,
            allow_insecure_localhost=args.allow_insecure_localhost,
            allow_custom_api_url=args.allow_custom_api_url,
        )
        destination = args.out or default_output(origin, args.owner, args.source)
        print(ocl_env.describe_target(origin, args.token, args.env))
        result = download_listing(
            origin=origin,
            owner_type=args.owner_type,
            owner=args.owner,
            source=args.source,
            token=args.token,
            destination=destination,
            page_size=args.page_size,
        )
        provenance = {
            "snapshot_type": "OCL concept listing (not a Source export)",
            "api_origin": origin,
            "owner_type": args.owner_type,
            "owner": args.owner,
            "source": args.source,
            "version_requested": "HEAD",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "token_sent": bool(args.token),
            "page_size": args.page_size,
            **result,
        }
        sidecar = destination.with_name(destination.name + ".provenance.json")
        sidecar.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        print(f"saved {destination} ({result['concepts']:,} concepts, sha256 {result['sha256']})")
        print(f"provenance: {sidecar}")
        return 0
    except ocl_http.OclHttpError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
