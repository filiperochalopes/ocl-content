"""Read-only hydration of the exact concepts a bulk import is about to update.

The Concept bulk importer is not a PATCH: it writes a new version and an omitted ``names`` or
``descriptions`` collection is replaced by an empty one. An artifact built only from the 2021
baseline therefore cannot be uploaded safely, because it would drop any live name, description,
or extra that the baseline does not carry. Hydration GETs each targeted concept from HEAD so the
generated update starts from the true current state; the token is used only for that read and is
never printed.

This module performs GET only. It contains no POST, PUT, PATCH, DELETE, import, or upload call.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

MNEMONIC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _segment(value: str, label: str) -> str:
    if not MNEMONIC.match(value or ""):
        raise ValueError(f"{label} is not a valid OCL mnemonic: {value!r}")
    return urllib.parse.quote(value, safe="")


def concept_url(api_url: str, owner: str, source: str, code: str) -> str:
    base = api_url.rstrip("/")
    return f"{base}/orgs/{_segment(owner, 'owner')}/sources/{_segment(source, 'source')}/concepts/{_segment(code, 'concept code')}/"


def _checked_base(api_url: str, allow_insecure_localhost: bool) -> str:
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme == "https":
        return api_url.rstrip("/")
    if parsed.scheme == "http" and allow_insecure_localhost and parsed.hostname in LOCAL_HOSTS:
        return api_url.rstrip("/")
    raise ValueError(
        f"refusing to send credentials to {api_url!r}: an https origin is required "
        "(an http localhost origin needs --allow-insecure-localhost)"
    )


def fetch_concept(
    api_url: str,
    owner: str,
    source: str,
    code: str,
    token: str,
    *,
    allow_insecure_localhost: bool = False,
    opener=urllib.request.urlopen,
    timeout: int = 60,
) -> dict:
    if not token:
        raise ValueError("a token is required to hydrate concepts from OCL")
    base = _checked_base(api_url, allow_insecure_localhost)
    request = urllib.request.Request(
        concept_url(base, owner, source, code),
        headers={"Authorization": f"Token {token}", "Accept": "application/json"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"GET {code} failed with HTTP {error.code}") from None


def hydrate(
    api_url: str,
    owner: str,
    source: str,
    codes: list[str],
    token: str,
    *,
    fetch=fetch_concept,
    allow_insecure_localhost: bool = False,
) -> tuple[dict[str, dict], list[dict]]:
    """Return ``({code: concept resource}, failures)``; failures are a hard stop for the caller."""
    resources: dict[str, dict] = {}
    failures: list[dict] = []
    for code in codes:
        try:
            resources[code] = fetch(
                api_url, owner, source, code, token, allow_insecure_localhost=allow_insecure_localhost
            )
        except Exception as error:  # noqa: BLE001 - reported, never hidden
            failures.append({"code": code, "error": str(error)})
    return resources, failures
