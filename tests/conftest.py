"""Shared test setup: put the repository root and ``tools/`` on ``sys.path``.

Terminology pipelines are imported by path through ``ocl_pipeline_loader.load(...)`` (for example
``load("icd/icd-10", "align")``), never as a top-level ``pipeline`` package, so several
terminologies can be tested in one pytest session.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "tools"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


# --- a throwaway OCL-like HTTP server on loopback, for the download tests -------------------------

import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import pytest  # noqa: E402


class FakeOcl:
    """Routes map a path to ``(status, headers, body)``; ``requests`` records what the tools sent."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[dict] = []
        self.url = ""


@pytest.fixture
def fake_ocl():
    state = FakeOcl()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            state.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
            status, headers, body = state.routes.get(self.path, (404, {}, b'{"detail": "not found"}'))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if status != 204:
                self.wfile.write(body)

        def log_message(self, *args):  # keep pytest output clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
