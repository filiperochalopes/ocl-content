"""Pinned input assets: fetch on demand and verify by SHA-256, shared by every terminology pipeline.

Fetched data files are never committed (see ``terminologies/.gitignore``); a registry keeps the URL,
the authority, the declared edition, and the expected hash in one place so an operator can re-obtain
a byte-identical copy. The hash — not TLS — is the integrity control, which matters for sources
served over plain HTTP. This module only downloads public input files; it never talks to OCL.
"""

from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Asset:
    key: str
    filename: str
    url: str
    sha256: str
    authority: str
    edition: str
    locale: str
    format: str
    destination: str


def verify(path: Path, asset: Asset) -> None:
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != asset.sha256:
        raise ValueError(
            f"{path} does not match the pinned SHA-256 for {asset.key}: expected {asset.sha256}, got {actual}"
        )


def fetch_asset(
    asset: Asset,
    assets_dir: Path,
    *,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> Path:
    """Download one asset into ``assets_dir`` and verify it before it is kept."""
    scheme = urlparse(asset.url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"{asset.key}: refusing to fetch a non-HTTP(S) URL: {asset.url}")
    target = Path(assets_dir) / asset.destination
    if target.is_file() and not force:
        verify(target, asset)
        print(f"ok (cached) {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with opener(asset.url, timeout=120) as response:
        payload = response.read()
    temporary.write_bytes(payload)
    try:
        verify(temporary, asset)
    except ValueError:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(target)
    print(f"ok {target} ({len(payload):,} bytes, sha256 verified)")
    return target
