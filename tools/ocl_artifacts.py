"""Shared mechanics for versioned bulk-import artifacts, used by every terminology pipeline.

Ordered NDJSON parts (each also written as a one-member upload ZIP capped by its COMPRESSED size), the whole bundle, a
single-member ``*.bundle.zip`` for direct full-bundle upload, and a ``*.parts.zip`` distribution archive containing
the individual part ZIPs plus a manifest. Only the bundle ZIP and audit are versioned; the parts ZIP, its nested upload
parts, and the raw bundle are deterministically regenerable and stay out of Git (see ``terminologies/.gitignore``).

Uploading is deliberately manual. Never upload ``*.parts.zip`` itself: extract it, then upload each inner
``*_part_NNN.zip`` (each contains exactly one NDJSON member) in order through the OCL bulk-import form. The
``*.bundle.zip`` also contains exactly one NDJSON member and can be uploaded as one import.

The compression method is selectable: ``deflate`` (level 9, maximum portability), ``bzip2``, or
``lzma`` (smallest for NDJSON but not readable by every archive tool).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "bulkimport_manifest.json"
ENVIRONMENTS = ("local", "staging", "production")


def upload_ready_map(local: bool, local_comment: str) -> dict:
    """Per-environment upload state recorded in every audit and manifest.

    ``upload_ready`` is a dict, not a bool, because each environment has its own validation state. Staging and
    production stay ``false`` until the local rehearsal has passed and that environment's own bundle is built.
    """
    return {
        "local": {"status": bool(local), "comment": local_comment},
        "staging": {"status": False, "comment": "pending: local rehearsal not passed; staging bundle not built"},
        "production": {"status": False, "comment": "pending: staging not validated; production bundle not built"},
    }
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
    files: list[Path],
    archive_name: str,
    manifest: dict | None = None,
    method: str = DEFAULT_METHOD,
) -> ArchiveInfo:
    """Create a deterministic ZIP from ``files`` and optionally add a JSON manifest."""
    if method not in METHODS:
        raise ValueError(f"unknown compression method {method!r}; use one of {', '.join(sorted(METHODS))}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / archive_name
    archive_path.unlink(missing_ok=True)

    payload_bytes = 0
    members: list[MemberInfo] = []
    compression = METHODS[method]
    with zipfile.ZipFile(archive_path, "w", compression, compresslevel=9) as archive:
        sources = [Path(source) for source in files]
        for source in sources:
            if not source.is_file():
                raise FileNotFoundError(f"cannot archive missing artifact: {source}")
            payload = source.read_bytes()
            payload_bytes += len(payload)
            info = zipfile.ZipInfo(source.name)
            info.compress_type = compression
            info.date_time = (1980, 1, 1, 0, 0, 0)
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
        if manifest is not None:
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
    upload_ready: dict,
    parts: list[dict],
    bundle: dict,
    method: str,
    bundle_archive: str,
    parts_archive: str,
) -> dict:
    """The manifest stored inside the parts distribution ZIP for the person doing the upload."""
    return {
        "schema_version": 1,
        "target": target,
        "mode": mode,
        "upload_ready": upload_ready,
        "compression": method,
        "upload": {
            "mechanism": "manual",
            "note": (
                "The .bundle.zip contains exactly one complete NDJSON file and can be uploaded as one import. "
                "The .parts.zip is a distribution container, not an OCL upload: extract it, then upload each "
                "inner bulkimport_part_NNN.zip in numeric order through the OCL form, reusing one Queue ID. "
                "Each inner part ZIP contains exactly one NDJSON file."
            ),
            "bundle_archive": bundle_archive,
            "parts_archive": parts_archive,
            "order": [part.get("zip") or part["name"] for part in parts],
        },
        "bundle": bundle,
        "parts": parts,
    }


# --- parts, bundle, and JSON writers ---

@dataclass(frozen=True)
class PartInfo:
    """One part. ``name``/``sha256``/``bytes`` describe the NDJSON; ``zip*`` describe the upload file."""

    name: str
    lines: int
    sha256: str
    bytes: int
    zip: str = ""
    zip_bytes: int = 0
    zip_sha256: str = ""


# The cap is on the COMPRESSED size of a part: an upload unit is a ZIP of at most this many bytes, so a
# large Source needs a handful of parts instead of hundreds of raw 2 MB files.
DEFAULT_PART_BYTES = 2 * 1024 * 1024
BUNDLE_NAME = "bulkimport_bundle.ndjson"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed, so re-zipping is reproducible
ESTIMATE_MARGIN = 48 * 1024  # headroom for what the compressor still buffers when the estimate stops


def serialize(line: dict) -> bytes:
    return (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def zip_payload(member: str, payload: bytes) -> bytes:
    """A deterministic deflate (level 9) ZIP holding one member: the form's upload unit."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        info = zipfile.ZipInfo(member, ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, payload, compresslevel=9)
    return buffer.getvalue()


def _cut(payloads: list[bytes], start: int, member: str, max_bytes: int, ids: list[str]) -> tuple[int, bytes]:
    """The longest run of lines from ``start`` whose real ZIP is at most ``max_bytes``.

    A streaming compressor estimates how many lines fit; the real ZIP is then built and, if it is
    still too big, the run is shortened until it fits. Parts are cut on resource boundaries only.
    """
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    budget = max(max_bytes - ESTIMATE_MARGIN, max_bytes // 2)
    produced, end = 0, start
    while end < len(payloads):
        produced += len(compressor.compress(payloads[end]))
        end += 1
        if produced >= budget:
            break
    while True:
        data = zip_payload(member, b"".join(payloads[start:end]))
        if len(data) <= max_bytes:
            return end, data
        if end - start == 1:
            raise ValueError(
                f"concept {ids[start]!r} compresses to {len(data):,} bytes, above the "
                f"{max_bytes:,}-byte part limit; a resource cannot be split across parts"
            )
        drop = max(1, (end - start) * (len(data) - max_bytes) // len(data) + 1)
        end = max(start + 1, end - drop)


def write_parts(
    out_dir: Path,
    lines: list[dict],
    max_bytes: int = DEFAULT_PART_BYTES,
    stem: str = "bulkimport_part",
) -> list[PartInfo]:
    """Write ``<stem>_001.ndjson`` and ``<stem>_001.zip`` (...) parts; each ZIP is at most ``max_bytes``.

    ``max_bytes`` is the COMPRESSED size of the upload file. Parts are cut on resource boundaries in
    the input order, so concatenating the NDJSON files in numeric order reproduces the bundle
    exactly. A single resource whose own ZIP exceeds the limit is an error: a resource is never
    split. Parts from a previous run with the same stem are removed first.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be 1 or more")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*out_dir.glob(f"{stem}_*.ndjson"), *out_dir.glob(f"{stem}_*.zip")]:
        stale.unlink()
    payloads = [serialize(line) for line in lines]
    ids = [str(line.get("id")) for line in lines]
    parts: list[PartInfo] = []
    start = 0
    while start < len(payloads):
        member = f"{stem}_{len(parts) + 1:03d}.ndjson"
        end, archive = _cut(payloads, start, member, max_bytes, ids)
        payload = b"".join(payloads[start:end])
        (out_dir / member).write_bytes(payload)
        zip_name = member[: -len(".ndjson")] + ".zip"
        (out_dir / zip_name).write_bytes(archive)
        parts.append(
            PartInfo(
                name=member, lines=end - start, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload),
                zip=zip_name, zip_bytes=len(archive), zip_sha256=hashlib.sha256(archive).hexdigest(),
            )
        )
        start = end
    return parts


def part_info_from_disk(ndjson: Path) -> PartInfo:
    """Describe a part already on disk, including its upload ZIP when one sits next to it."""
    ndjson = Path(ndjson)
    payload = ndjson.read_bytes()
    archive = ndjson.with_suffix(".zip")
    extra = {}
    if archive.is_file():
        data = archive.read_bytes()
        extra = {"zip": archive.name, "zip_bytes": len(data), "zip_sha256": hashlib.sha256(data).hexdigest()}
    return PartInfo(name=ndjson.name, lines=payload.count(b"\n"), sha256=hashlib.sha256(payload).hexdigest(),
                    bytes=len(payload), **extra)


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
