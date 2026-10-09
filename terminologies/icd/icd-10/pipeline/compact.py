"""Pack the generated artifacts into one versioned zip: the parts plus the whole bundle.

Only the zip is versioned. The parts and the bundle are deterministically regenerable and are
large, so they stay out of Git (see ``terminologies/.gitignore``); the zip carries them compressed
together with a manifest that records the target, the mode, whether the artifact is upload-ready,
and the SHA-256 of every part.

Uploading is deliberately manual. Nothing here — and nothing in this pipeline — calls an OCL
upload or bulk-import endpoint; an operator extracts the parts and uploads them in order through
the OCL bulk-import form.

The compression method is selectable: ``deflate`` (level 9, maximum portability), ``bzip2``, or
``lzma`` (smallest for NDJSON but not readable by every archive tool).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "bulkimport_manifest.json"
METHODS: dict[str, int] = {
    "deflate": zipfile.ZIP_DEFLATED,
    "bzip2": zipfile.ZIP_BZIP2,
    "lzma": zipfile.ZIP_LZMA,
}
DEFAULT_METHOD = "deflate"


@dataclass(frozen=True)
class MemberInfo:
    name: str
    lines: int
    bytes: int
    compressed_bytes: int
    sha256: str


@dataclass(frozen=True)
class ArchiveInfo:
    name: str
    bytes: int
    method: str
    members: list[MemberInfo]
    payload_bytes: int

    @property
    def ratio(self) -> float:
        return self.bytes / self.payload_bytes if self.payload_bytes else 0.0


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def create_archive(
    out_dir: Path,
    *,
    parts: list[Path],
    bundle: Path,
    manifest: dict,
    archive_name: str,
    method: str = DEFAULT_METHOD,
) -> ArchiveInfo:
    """Zip ``parts`` (in the given order) plus ``bundle`` and the manifest."""
    if method not in METHODS:
        raise ValueError(f"unknown compression method {method!r}; use one of {', '.join(sorted(METHODS))}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / archive_name
    if archive_path.exists():
        archive_path.unlink()

    payload_bytes = 0
    members: list[MemberInfo] = []
    compression = METHODS[method]
    with zipfile.ZipFile(archive_path, "w", compression, compresslevel=9) as archive:
        sources = [Path(part) for part in parts] + [Path(bundle)]
        for source in sources:
            if not source.is_file():
                raise FileNotFoundError(f"cannot archive missing artifact: {source}")
            payload = source.read_bytes()
            payload_bytes += len(payload)
            info = zipfile.ZipInfo(source.name)
            info.compress_type = compression
            info.date_time = (1980, 1, 1, 0, 0, 0)  # fixed, so re-zipping is reproducible
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload, compresslevel=9)
            entry = archive.getinfo(source.name)
            members.append(
                MemberInfo(
                    name=source.name,
                    lines=_count_lines(payload),
                    bytes=len(payload),
                    compressed_bytes=entry.compress_size,
                    sha256=sha256_bytes(payload),
                )
            )
        manifest_payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        payload_bytes += len(manifest_payload)
        info = zipfile.ZipInfo(MANIFEST_NAME)
        info.compress_type = compression
        info.date_time = (1980, 1, 1, 0, 0, 0)
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_payload, compresslevel=9)
        entry = archive.getinfo(MANIFEST_NAME)
        members.append(
            MemberInfo(
                name=MANIFEST_NAME,
                lines=0,
                bytes=len(manifest_payload),
                compressed_bytes=entry.compress_size,
                sha256=sha256_bytes(manifest_payload),
            )
        )
    return ArchiveInfo(
        name=archive_name,
        bytes=archive_path.stat().st_size,
        method=method,
        members=members,
        payload_bytes=payload_bytes,
    )


def _count_lines(payload: bytes) -> int:
    return payload.count(b"\n")


def build_manifest(
    *,
    target: dict,
    mode: str,
    upload_ready: bool,
    generated_at: str,
    parts: list[dict],
    bundle: dict,
    method: str,
) -> dict:
    """The manifest stored inside the archive, aimed at the human doing the upload."""
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready,
        "compression": method,
        "upload": {
            "mechanism": "manual",
            "note": (
                "No tool in this repository uploads to OCL. Extract the parts and upload them in "
                "numeric order through the OCL bulk-import form, reusing one Queue ID."
            ),
            "order": [part["name"] for part in parts],
        },
        "bundle": bundle,
        "parts": parts,
    }
