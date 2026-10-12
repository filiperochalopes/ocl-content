"""tools/ocl_export_download.py: read-only export download with provenance."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

import ocl_export_download as subject

TOKEN = "super-secret-token"
EXPORT_PATH = "/orgs/WHO/sources/ICD-10-WHO/HEAD/export/"


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def run(fake_ocl, tmp_path, *extra, token=TOKEN):
    args = ["--owner", "WHO", "--source", "ICD-10-WHO", "--api-url", fake_ocl.url, "--allow-insecure-localhost",
            "--out", str(tmp_path / "out" / "export.zip"), *extra]
    if token:
        args += ["--token", token]
    return subject.main(args)


def test_downloads_the_export_and_records_provenance(fake_ocl, tmp_path, capsys):
    payload = make_zip({"export.json": b'{"concepts": []}'})
    fake_ocl.routes[EXPORT_PATH] = (200, {}, payload)
    assert run(fake_ocl, tmp_path) == 0
    assert (tmp_path / "out" / "export.zip").read_bytes() == payload
    sidecar = json.loads((tmp_path / "out" / "export.zip.provenance.json").read_text(encoding="utf-8"))
    assert sidecar["owner"] == "WHO" and sidecar["source"] == "ICD-10-WHO" and sidecar["version"] == "HEAD"
    assert sidecar["token_sent"] is True and sidecar["members"] == ["export.json"] and sidecar["bytes"] == len(payload)
    assert TOKEN not in json.dumps(sidecar)
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "token: set" in out.out


def test_it_issues_only_get_requests_and_never_asks_for_generation(fake_ocl, tmp_path):
    fake_ocl.routes[EXPORT_PATH] = (204, {}, b"")
    assert run(fake_ocl, tmp_path) == 3
    assert [request["path"] for request in fake_ocl.requests] == [EXPORT_PATH]  # one GET, no trigger


def test_no_ready_export_explains_itself(fake_ocl, tmp_path, capsys):
    fake_ocl.routes[EXPORT_PATH] = (204, {}, b"")
    run(fake_ocl, tmp_path)
    assert "never asks the server to generate" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_authentication_failure_points_at_the_token(fake_ocl, tmp_path, capsys):
    fake_ocl.routes[EXPORT_PATH] = (403, {}, b'{"detail": "Authentication required. Anonymous API access is disabled."}')
    assert run(fake_ocl, tmp_path, token=None) == 4
    assert "OCL_API_TOKEN" in capsys.readouterr().err


def test_a_response_that_is_not_an_export_zip_is_discarded(fake_ocl, tmp_path):
    fake_ocl.routes[EXPORT_PATH] = (200, {}, b"<html>not a zip</html>")
    assert run(fake_ocl, tmp_path) == 2
    assert not (tmp_path / "out" / "export.zip").exists()
    fake_ocl.routes[EXPORT_PATH] = (200, {}, make_zip({"other.txt": b"x"}))
    assert run(fake_ocl, tmp_path) == 2
    assert not (tmp_path / "out" / "export.zip").exists()


def test_an_existing_file_is_never_overwritten(fake_ocl, tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "export.zip").write_bytes(b"keep")
    fake_ocl.routes[EXPORT_PATH] = (200, {}, make_zip({"export.json": b"{}"}))
    assert run(fake_ocl, tmp_path) == 2
    assert (tmp_path / "out" / "export.zip").read_bytes() == b"keep" and fake_ocl.requests == []


def test_the_guard_refuses_an_unapproved_origin_before_any_request(tmp_path, capsys):
    assert subject.main(["--owner", "WHO", "--source", "ICD-10-WHO", "--api-url", "http://api.ocl.localhost",
                         "--token", TOKEN, "--out", str(tmp_path / "x.zip")]) == 2
    assert "HTTPS" in capsys.readouterr().err
    assert subject.main(["--owner", "WHO", "--source", "ICD-10-WHO", "--api-url", "https://staging.example.org",
                         "--token", TOKEN, "--out", str(tmp_path / "x.zip")]) == 2


@pytest.mark.parametrize("owner,source,version", [("W/HO", "S", "HEAD"), ("WHO", "../x", "HEAD"), ("WHO", "S", "v 1")])
def test_identifiers_are_validated(owner, source, version, tmp_path):
    code = subject.main(["--owner", owner, "--source", source, "--version", version, "--api-url",
                         "https://api.openconceptlab.org", "--token", TOKEN, "--out", str(tmp_path / "x.zip")])
    assert code == 2


def test_export_url_and_default_output_keep_instances_apart():
    url = subject.export_url("http://api.ocl.localhost", "orgs", "WHO", "ICD-10-WHO", "HEAD")
    assert url == "http://api.ocl.localhost/orgs/WHO/sources/ICD-10-WHO/HEAD/export/"
    local = subject.default_output("http://api.ocl.localhost", "WHO", "ICD-10-WHO", "HEAD")
    prod = subject.default_output("https://api.openconceptlab.org", "WHO", "ICD-10-WHO", "HEAD")
    assert local != prod and local.parent.name == "api.ocl.localhost" and prod.parent.name == "api.openconceptlab.org"


def test_the_tool_has_no_write_surface():
    source = (subject.REPO_ROOT / "tools" / "ocl_export_download.py").read_text(encoding="utf-8")
    for marker in ('method="POST"', 'method="PUT"', 'method="PATCH"', 'method="DELETE"', "--apply", "--upload"):
        assert marker not in source
