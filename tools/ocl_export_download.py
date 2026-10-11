#!/usr/bin/env python3
"""Download the export of any OCL Source version, read-only.

    # production snapshot of WHO/ICD-10-WHO (settings from .env.production)
    python3 tools/ocl_export_download.py --env-file .env.production --owner WHO --source ICD-10-WHO

    # the same Source on a local instance, after an update (settings from .env.local)
    python3 tools/ocl_export_download.py --env-file .env.local --owner WHO --source ICD-10-WHO \\
        --out exports/after/WHO_ICD-10-WHO_HEAD.zip

It issues GET requests only. It never asks OCL to *generate* an export (that is a POST, and the
server's decision): a 204 means "no export is ready yet" and the tool stops with that message.
It never overwrites a file, writes ``<name>.part`` first and renames at the end, refuses a
download that is not a ZIP holding ``export.json``, and records the SHA-256 and the origin in a
``<name>.provenance.json`` next to it. The token is sent only to the validated API origin; a
redirect to pre-signed storage is followed once, without the token (see ``ocl_http.download``).

Exit codes: 0 downloaded, 2 refused or failed, 3 no export ready, 4 authentication required.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocl_env  # noqa: E402
import ocl_http  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORTS_DIR = REPO_ROOT / "exports"
OWNER_TYPES = ("orgs", "users")


def export_url(origin: str, owner_type: str, owner: str, source: str, version: str) -> str:
    for label, value in (("owner", owner), ("source", source), ("version", version)):
        if not ocl_http.OCL_IDENTIFIER_RE.fullmatch(value or ""):
            raise ocl_http.OclHttpError(f"{label} must use OCL identifier characters: {value!r}")
    if owner_type not in OWNER_TYPES:
        raise ocl_http.OclHttpError(f"owner type must be one of {OWNER_TYPES}")
    return f"{origin}/{owner_type}/{quote(owner, safe='')}/sources/{quote(source, safe='')}/{quote(version, safe='')}/export/"


def default_output(origin: str, owner: str, source: str, version: str) -> Path:
    """``exports/<host>/<owner>_<source>_<version>.zip``: the host keeps production and local apart."""
    host = (urlparse(origin).netloc or "unknown").replace(":", "_")
    return EXPORTS_DIR / host / f"{owner}_{source}_{version}.zip"


def check_archive(path: Path) -> list[str]:
    """Return the member names, or raise when the file is not a ZIP holding ``export.json``."""
    if not zipfile.is_zipfile(path):
        raise ocl_http.OclHttpError(f"{path.name} is not a ZIP archive; the server did not return an export")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    if "export.json" not in names:
        raise ocl_http.OclHttpError(f"{path.name} holds no export.json (members: {names[:5]})")
    return names


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env = ocl_env.bootstrap(argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", required=True, help="owner mnemonic, for example WHO")
    parser.add_argument("--source", required=True, help="Source mnemonic, for example ICD-10-WHO")
    parser.add_argument("--version", default="HEAD", help="Source version id (default: HEAD)")
    parser.add_argument("--owner-type", choices=OWNER_TYPES, default="orgs")
    parser.add_argument("--out", type=Path, help="destination ZIP (default: exports/<host>/<owner>_<source>_<version>.zip)")
    parser.add_argument("--env-file", type=Path, help="env file with OCL_API_URL / OCL_API_TOKEN (default: .env)")
    parser.add_argument("--api-url", default=os.getenv("OCL_API_URL", ocl_http.DEFAULT_API_URL))
    parser.add_argument("--token", default=os.getenv("OCL_API_TOKEN"), help="default: OCL_API_TOKEN")
    parser.add_argument("--allow-custom-api-url", action="store_true", help="allow an https origin other than production")
    parser.add_argument("--allow-insecure-localhost", action="store_true", help="allow http for localhost and *.localhost")
    args = parser.parse_args(argv)
    args.env = env
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        origin = ocl_http.validate_api_url(
            args.api_url,
            allow_insecure_localhost=args.allow_insecure_localhost,
            allow_custom_api_url=args.allow_custom_api_url,
        )
        url = export_url(origin, args.owner_type, args.owner, args.source, args.version)
        destination = args.out or default_output(origin, args.owner, args.source, args.version)
        print(ocl_env.describe_target(origin, args.token, args.env))
        print(f"GET {url}")
        result = ocl_http.download(
            url, destination, args.token, allow_insecure_localhost=args.allow_insecure_localhost
        )
        if result.status == 204:
            print(
                "no export is ready for this version (HTTP 204). Generate it in OCL and run this again; "
                "this tool never asks the server to generate one.",
                file=sys.stderr,
            )
            return 3
        try:
            members = check_archive(destination)
        except ocl_http.OclHttpError:
            destination.unlink(missing_ok=True)
            raise
        provenance = {
            "api_origin": origin,
            "url": url,
            "owner_type": args.owner_type,
            "owner": args.owner,
            "source": args.source,
            "version": args.version,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "token_sent": bool(args.token),
            "redirected_to_host": result.redirected_to,
            "bytes": result.bytes,
            "sha256": result.sha256,
            "members": members,
        }
        sidecar = destination.with_name(destination.name + ".provenance.json")
        sidecar.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        print(f"saved {destination}  ({result.bytes:,} bytes, sha256 {result.sha256})")
        print(f"provenance: {sidecar}")
        return 0
    except ocl_http.OclHttpError as error:
        print(f"error: {error}", file=sys.stderr)
        if error.status in (401, 403):
            print(
                "hint: the server requires authentication; set OCL_API_TOKEN in the env file or the shell "
                "(production also disables anonymous reads).",
                file=sys.stderr,
            )
            return 4
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
