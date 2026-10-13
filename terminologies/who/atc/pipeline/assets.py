"""Pinned inputs for WHO-ATC: the BioPortal ATC ontology export (Turtle) and the atcddd.fhi.no
cumulative alterations list.

The ATC ontology is **not** a plain anonymous download like the WHO ICD-11 Simple Tabulation: a
BioPortal submission download needs a personal API key in the query string
(``?apikey=...``), so this does not fit `tools/ocl_assets.py`'s public-URL-plus-hash ``Asset`` shape.
Instead:

- a BioPortal *submission* is immutable once published, so a specific numbered submission is pinned
  by its own SHA-256 in ``PINNED_SUBMISSIONS`` below, the same integrity contract as every other
  pipeline's assets;
- the Turtle file is fetched with ``BIOPORTAL_API_KEY`` (free to obtain, personal — never printed,
  never committed) when set, and otherwise this function expects a copy already placed by hand at
  the same path a curator already uses today (downloaded from
  https://bioportal.bioontology.org/ontologies/ATC in a browser);
- the atcddd.fhi.no cumulative alterations list needs no key and is fetched directly. It is **not**
  hash-pinned: WHO/FHI append to it every year, so a re-fetch is expected to differ from a previous
  one; the build records the SHA-256 of whichever copy was actually used, for provenance, not as a
  gate.

Neither file is committed (see ``terminologies/.gitignore``); this module makes no OCL call.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BIOPORTAL_SUBMISSION_URL_TEMPLATE = "https://data.bioontology.org/ontologies/ATC/submissions/{submission}/download"
ALTERATIONS_URL = "https://atcddd.fhi.no/atc_ddd_alterations__cumulative/atc_alterations/"

# One entry per BioPortal submission this project has verified by hash. Re-downloading the same
# submission id always reproduces the same bytes (a submission is immutable once published), so the
# hash is the integrity control — the same role `tools/ocl_assets.py` gives every other pipeline.
PINNED_SUBMISSIONS: dict[int, dict[str, str]] = {
    25: {
        "sha256": "af99bc159c72f0ef70c18065d68f61022bf6074efe65585eb5e826527dbcec4a",
        "version_info": "2025_02_10",
        "umls_source": "UMLS 2025AB",
        "fetched_on": "2026-10-12",
    },
}
LATEST_SUBMISSION = 25


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    pinned: bool  # True when the hash matched a submission already recorded in PINNED_SUBMISSIONS


def ttl_destination(assets_dir: Path, submission: int = LATEST_SUBMISSION) -> Path:
    return Path(assets_dir) / "bioportal" / f"submission-{submission}" / "ATC.ttl"


def fetch_ttl(
    assets_dir: Path,
    *,
    submission: int = LATEST_SUBMISSION,
    api_key: str | None = None,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> FetchResult:
    """Verify an already-placed copy, or download one with a BioPortal API key.

    ``api_key`` defaults to ``$BIOPORTAL_API_KEY``. When neither a key nor a cached file is
    available, this raises with instructions instead of attempting a request BioPortal would reject.
    """
    target = ttl_destination(assets_dir, submission)
    key = api_key or os.environ.get("BIOPORTAL_API_KEY")
    pinned_entry = PINNED_SUBMISSIONS.get(submission)

    if target.is_file() and not force:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if pinned_entry and digest != pinned_entry["sha256"]:
            raise ValueError(
                f"{target} does not match the pinned SHA-256 for BioPortal ATC submission {submission}: "
                f"expected {pinned_entry['sha256']}, got {digest}. Re-fetch with --force, or record a new "
                "pinned submission here if BioPortal genuinely republished this submission id."
            )
        print(f"ok (cached) {target}")
        return FetchResult(path=target, sha256=digest, pinned=pinned_entry is not None)

    if not key:
        raise RuntimeError(
            f"BIOPORTAL_API_KEY is not set and no cached copy exists at {target}. Either export "
            "BIOPORTAL_API_KEY (free at https://bioportal.bioontology.org/account) or place the "
            "Turtle file you already downloaded by hand at that exact path."
        )
    url = BIOPORTAL_SUBMISSION_URL_TEMPLATE.format(submission=submission) + f"?apikey={key}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with opener(url, timeout=120) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if pinned_entry and digest != pinned_entry["sha256"]:
        raise ValueError(
            f"downloaded BioPortal ATC submission {submission} does not match the pinned SHA-256: "
            f"expected {pinned_entry['sha256']}, got {digest}"
        )
    temporary.write_bytes(payload)
    temporary.replace(target)
    print(f"ok {target} ({len(payload):,} bytes, sha256={digest[:12]}...)")
    return FetchResult(path=target, sha256=digest, pinned=pinned_entry is not None)


def alterations_destination(assets_dir: Path) -> Path:
    return Path(assets_dir) / "atcddd" / "atc_alterations_cumulative.html"


def fetch_alterations(assets_dir: Path, *, force: bool = False, opener=urllib.request.urlopen) -> Path:
    target = alterations_destination(assets_dir)
    if target.is_file() and not force:
        print(f"ok (cached) {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with opener(ALTERATIONS_URL, timeout=60) as response:
        payload = response.read()
    temporary.write_bytes(payload)
    temporary.replace(target)
    print(f"ok {target} ({len(payload):,} bytes)")
    return target
