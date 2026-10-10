"""Shared mechanics for versioned bulk-import artifacts, used by every terminology pipeline.

Ordered, size-capped NDJSON parts, the whole bundle, a manifest, and the one zip that holds them.
Only the zip and the audit are versioned; the parts and the bundle are deterministically
regenerable and stay out of Git (see ``terminologies/.gitignore``).

Uploading is deliberately manual. Nothing here — and nothing in any pipeline — calls an OCL
upload or bulk-import endpoint; an operator extracts the parts and uploads them in order through
the OCL bulk-import form. This module performs no network call.

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
    parts: list[dict],
    bundle: dict,
    method: str,
) -> dict:
    """The manifest stored inside the archive, aimed at the human doing the upload."""
    return {
        "schema_version": 1,
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


# --- parts, bundle, and JSON writers ---

@dataclass(frozen=True)
class PartInfo:
    name: str
    lines: int
    sha256: str
    bytes: int


DEFAULT_PART_BYTES = 2 * 1024 * 1024
BUNDLE_NAME = "bulkimport_bundle.ndjson"


def serialize(line: dict) -> bytes:
    return (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _flush(out_dir: Path, stem: str, index: int, chunks: list[bytes]) -> PartInfo:
    payload = b"".join(chunks)
    name = f"{stem}_{index:03d}.ndjson"
    (out_dir / name).write_bytes(payload)
    return PartInfo(name=name, lines=len(chunks), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def write_parts(
    out_dir: Path,
    lines: list[dict],
    max_bytes: int = DEFAULT_PART_BYTES,
    stem: str = "bulkimport_part",
) -> list[PartInfo]:
    """Write ``<stem>_001.ndjson`` (…) parts, each at most ``max_bytes`` of serialized payload.

    Parts are cut on resource boundaries in the input order, so concatenating them in numeric
    order reproduces the bundle exactly. A single resource larger than the limit is an error:
    a resource is never split. Parts from a previous run with the same stem are removed first.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be 1 or more")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"{stem}_*.ndjson"):
        stale.unlink()
    parts: list[PartInfo] = []
    chunks: list[bytes] = []
    size = 0
    for line in lines:
        payload = serialize(line)
        if len(payload) > max_bytes:
            raise ValueError(
                f"concept {line.get('id')!r} serializes to {len(payload):,} bytes, above the "
                f"{max_bytes:,}-byte part limit; a resource cannot be split across parts"
            )
        if chunks and size + len(payload) > max_bytes:
            parts.append(_flush(out_dir, stem, len(parts) + 1, chunks))
            chunks, size = [], 0
        chunks.append(payload)
        size += len(payload)
    if chunks:
        parts.append(_flush(out_dir, stem, len(parts) + 1, chunks))
    return parts


def write_bundle(out_dir: Path, lines: list[dict], name: str = BUNDLE_NAME) -> PartInfo:
    """Write the complete bundle: every line, in order, as one NDJSON file."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = b"".join(serialize(line) for line in lines)
    (out_dir / name).write_bytes(payload)
    return PartInfo(name=name, lines=len(lines), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
