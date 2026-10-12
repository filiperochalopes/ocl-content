"""Offline reading of an OCL Source export, shared by every tool that starts from a snapshot.

Accepted inputs: the ``export.json`` of a Source version (a JSON object with a ``concepts`` list),
an NDJSON file with one Concept resource per line, or a ``.zip`` holding one of those. Nothing here
touches the network: a pipeline or verifier that reads an export needs no token and no API client.

An export is a snapshot, not live HEAD. Take it shortly before building an update, and keep its
SHA-256: the audit and the verification report record it so a result names the snapshot it used.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

MEMBER_SUFFIXES = (".json", ".ndjson", ".jsonl")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bytes(path: Path) -> bytes:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"export not found: {path}")
    if path.suffix.lower() != ".zip":
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(MEMBER_SUFFIXES)]
        if not members:
            raise ValueError(f"{path}: no .json/.ndjson/.jsonl member in the archive")
        preferred = [name for name in members if Path(name).name == "export.json"]
        return archive.read((preferred or sorted(members))[0])


def concept_resources(payload: bytes, origin: Path) -> list[dict]:
    text = payload.decode("utf-8-sig")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict):
        concepts = document.get("concepts")
        if not isinstance(concepts, list):
            raise ValueError(f"{origin}: JSON export has no 'concepts' list")
        return [item for item in concepts if isinstance(item, dict)]
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    resources: list[dict] = []
    for number, line in enumerate(io.StringIO(text), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{origin} line {number}: not valid JSON ({error})") from None
        if isinstance(item, dict) and item.get("type", "Concept") == "Concept":
            resources.append(item)
    return resources


def load_concepts(path: Path, owner: str, source: str) -> dict[str, dict]:
    """Return ``{concept id: resource}`` for every Concept in the export.

    A resource that names a different owner or Source is refused, so an export of the wrong
    repository cannot silently seed an update or a verification. Two resources with the same id
    are an error.
    """
    path = Path(path)
    concepts: dict[str, dict] = {}
    for resource in concept_resources(read_bytes(path), path):
        if resource.get("type", "Concept") != "Concept":
            continue
        concept_id = str(resource.get("id") or "")
        if not concept_id:
            raise ValueError(f"{path}: concept resource without an id")
        for key, expected in (("owner", owner), ("source", source)):
            actual = resource.get(key)
            if actual is not None and actual != expected:
                raise ValueError(f"{path}: concept {concept_id!r} belongs to {key} {actual!r}, expected {expected!r}")
        if concept_id in concepts:
            raise ValueError(f"{path}: concept {concept_id!r} appears more than once")
        concepts[concept_id] = resource
    return concepts
