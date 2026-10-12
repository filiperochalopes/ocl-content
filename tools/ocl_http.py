"""Shared, read-only HTTP guard for the OCL tools in this repository.

Any tool that sends an OCL token must go through this module so the same rules hold everywhere:
the token only reaches an approved origin, and a redirect can never carry it somewhere else. It
exposes GET only; no tool in this repository writes to OCL over HTTP.

The module is named ``ocl_http`` on purpose: a top-level ``http`` module in ``tools/`` would
shadow the standard library package that ``urllib`` imports.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_API_URL = "https://api.openconceptlab.org"
LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}
LOCALHOST_SUFFIX = ".localhost"  # RFC 6761: every *.localhost name is reserved for loopback
OCL_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9._@-]+$")
REDIRECT_CODES = {301, 302, 303, 307, 308}
CHUNK_BYTES = 1 << 20


class OclHttpError(ValueError):
    """Raised when a request is refused by the guard or fails; ``status`` is the HTTP code, if any."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    """Reject all redirects so an Authorization header cannot leave the approved origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_loopback_host(hostname: str | None) -> bool:
    """True for localhost, 127.0.0.1, ::1, and any ``*.localhost`` name (for example ``api.ocl.localhost``)."""
    host = (hostname or "").lower().rstrip(".")
    return host in LOCALHOST_NAMES or host.endswith(LOCALHOST_SUFFIX)


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
    if parsed.scheme == "http" and is_loopback_host(parsed.hostname) and allow_insecure_localhost:
        return origin
    raise OclHttpError("OCL API URL must use HTTPS; HTTP is allowed only for explicit localhost development")


def error_detail(exc: HTTPError, limit: int = 300) -> str:
    """A readable message from an error response, never raw binary.

    OCL renders an error through the negotiated format, so a request that asked for
    ``application/zip`` gets the error JSON wrapped in a small ZIP. Unwrap it; anything else that is
    not text is summarized by size and type instead of being printed.
    """
    try:
        body = exc.read(65536)
    except Exception:  # noqa: BLE001 - a failed read must not hide the original HTTP error
        return ""
    kind = (exc.headers.get("Content-Type") if exc.headers else "") or "binary data"
    if body[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = archive.namelist()
                if names:
                    body = archive.read(names[0])[:65536]
        except (zipfile.BadZipFile, OSError):
            return f"<{len(body)} bytes of {kind}>"
    text = body.decode("utf-8", errors="replace")
    printable = sum(1 for char in text if char.isprintable() or char in "\r\n\t")
    if not text.strip() or printable / len(text) < 0.95:
        return f"<{len(body)} bytes of {kind}>"
    return text.strip()[:limit]


def _authorization(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Token {token}"} if token else {}


def get_json(url: str, token: str | None = None, *, timeout: int = 60) -> dict[str, Any]:
    """GET ``url`` as JSON. Redirects are rejected; the caller validates the origin first."""
    request = Request(url, headers={"Accept": "application/json", **_authorization(token)}, method="GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise OclHttpError(f"GET {url} failed with HTTP {exc.code}: {error_detail(exc)}", status=exc.code) from exc
    except URLError as exc:
        raise OclHttpError(f"GET {url} failed: {exc.reason}") from exc
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OclHttpError(f"GET {url} returned non-JSON content") from exc


@dataclass(frozen=True)
class Download:
    status: int  # 200 when a file was written, 204 when the server has nothing ready
    path: Path | None
    bytes: int
    sha256: str
    redirected_to: str | None  # host only, never the full (possibly signed) URL


def _redirect_target(location: str, base_url: str, *, allow_insecure_localhost: bool) -> str:
    target = urlparse(urljoin(base_url, location))
    if target.scheme == "https":
        return target.geturl()
    if target.scheme == "http" and allow_insecure_localhost and is_loopback_host(target.hostname):
        return target.geturl()
    raise OclHttpError(f"refusing to follow a redirect to {target.scheme}://{target.hostname}: https is required")


def download(
    url: str,
    destination: Path,
    token: str | None = None,
    *,
    accept: str = "application/zip",
    allow_insecure_localhost: bool = False,
    timeout: int = 600,
) -> Download:
    """Stream ``url`` to ``destination`` without ever overwriting a file or leaking the token.

    The first request carries the token and rejects redirects. OCL may answer with a redirect to a
    pre-signed storage URL; that single hop is followed **without** the Authorization header, only
    over https (or loopback http when allowed), and a second redirect is refused. A 204 means the
    server has nothing ready and nothing is written. The file is written to ``<name>.part`` and
    renamed only after the last byte arrived.
    """
    destination = Path(destination)
    if destination.exists():
        raise OclHttpError(f"refusing to overwrite an existing file: {destination}")
    opener = build_opener(NoRedirect())
    headers = {"Accept": accept}
    redirected_to: str | None = None
    try:
        try:
            response = opener.open(Request(url, headers={**headers, **_authorization(token)}), timeout=timeout)
        except HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code not in REDIRECT_CODES or not location:
                raise OclHttpError(f"GET {url} failed with HTTP {exc.code}: {error_detail(exc)}", status=exc.code) from exc
            target = _redirect_target(location, url, allow_insecure_localhost=allow_insecure_localhost)
            redirected_to = urlparse(target).hostname
            try:  # the second hop never carries the Authorization header
                response = opener.open(Request(target, headers=headers), timeout=timeout)
            except HTTPError as second:
                raise OclHttpError(
                    f"the redirected download failed with HTTP {second.code}", status=second.code
                ) from second
        with response:
            if response.status == 204:
                return Download(204, None, 0, hashlib.sha256().hexdigest(), redirected_to)
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + ".part")
            digest, size = hashlib.sha256(), 0
            try:
                with partial.open("xb") as stream:
                    for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                        stream.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
            return Download(response.status, destination, size, digest.hexdigest(), redirected_to)
    except URLError as exc:
        raise OclHttpError(f"GET {url} failed: {exc.reason}") from exc
