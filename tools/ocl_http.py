"""Shared, read-only HTTP guard for the OCL tools in this repository.

Any tool that sends an OCL token must go through this module so the same two rules hold
everywhere: the token only reaches an approved origin, and a redirect can never carry it
somewhere else. It exposes GET only; no tool in this repository writes to OCL over HTTP.

The module is named ``ocl_http`` on purpose: a top-level ``http`` module in ``tools/`` would
shadow the standard library package that ``urllib`` imports.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_API_URL = "https://api.openconceptlab.org"
LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}
OCL_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9._@-]+$")


class OclHttpError(ValueError):
    """Raised when a request is refused by the guard or fails."""


class NoRedirect(HTTPRedirectHandler):
    """Reject all redirects so an Authorization header cannot leave the approved origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_api_url(
    api_url: str, *, allow_insecure_localhost: bool = False, allow_custom_api_url: bool = False
) -> str:
    """Return the normalized origin, or raise ``OclHttpError`` when a token must not be sent there."""
    parsed = urlparse(api_url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OclHttpError("OCL API URL must be an origin without credentials, query, or fragment")
    if parsed.path not in ("", "/"):
        raise OclHttpError("OCL API URL must not include a path")
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if parsed.scheme == "https":
        if origin != DEFAULT_API_URL and not allow_custom_api_url:
            raise OclHttpError("a custom OCL API URL requires --allow-custom-api-url")
        return origin
    if parsed.scheme == "http" and parsed.hostname in LOCALHOST_NAMES and allow_insecure_localhost:
        return origin
    raise OclHttpError("OCL API URL must use HTTPS; HTTP is allowed only for explicit localhost development")


def get_json(url: str, token: str | None = None, *, timeout: int = 60) -> dict[str, Any]:
    """GET ``url`` as JSON. Redirects are rejected; the caller validates the origin first."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise OclHttpError(f"GET {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise OclHttpError(f"GET {url} failed: {exc.reason}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OclHttpError(f"GET {url} returned non-JSON content") from exc
