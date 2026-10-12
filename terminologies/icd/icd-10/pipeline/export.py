"""Offline reading of an OCL Source export, used to start a bulk update from the live state.

The Concept bulk importer is not a PATCH: it writes a new version and an omitted ``names`` or
``descriptions`` collection is replaced by an empty one. An artifact built only from the 2021
baseline therefore cannot be uploaded safely, because it would drop any live name, description,
or extra that the baseline does not carry. The pipeline reads the current state of the targeted
concepts from an export of the Source instead of calling the API, so it needs no token and no
network access: no rate limit, no retry policy, and no credential to guard.

The reader itself is shared with the verifier (``tools/ocl_export.py``); take the export shortly
before uploading, because anything changed in OCL after it was taken is overwritten by the update.
"""

from __future__ import annotations

from ocl_export import load_concepts  # noqa: F401 - re-exported: this module is the pipeline's export API


def select(concepts: dict[str, dict], codes: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Return ``({code: resource}, missing)``; a missing code is a hard stop for the caller."""
    found = {code: concepts[code] for code in codes if code in concepts}
    missing = [{"code": code, "error": "not present in the export"} for code in codes if code not in concepts]
    return found, missing
