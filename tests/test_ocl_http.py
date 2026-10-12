"""The shared HTTP guard: origins, loopback names, and downloads that never leak the token."""

from __future__ import annotations

import pytest

import ocl_http

TOKEN = "super-secret-token"


def test_dot_localhost_names_are_loopback():
    assert ocl_http.is_loopback_host("api.ocl.localhost")
    assert ocl_http.is_loopback_host("API.OCL.LOCALHOST.")
    assert ocl_http.is_loopback_host("127.0.0.1") and ocl_http.is_loopback_host("localhost")
    assert not ocl_http.is_loopback_host("localhost.evil.example") and not ocl_http.is_loopback_host("evillocalhost")


def test_a_local_instance_needs_the_explicit_http_opt_in():
    assert ocl_http.validate_api_url("http://api.ocl.localhost", allow_insecure_localhost=True) == "http://api.ocl.localhost"
    with pytest.raises(ocl_http.OclHttpError, match="HTTPS"):
        ocl_http.validate_api_url("http://api.ocl.localhost")
    with pytest.raises(ocl_http.OclHttpError, match="HTTPS"):
        ocl_http.validate_api_url("http://api.ocl.example", allow_insecure_localhost=True)


def test_download_writes_the_file_and_sends_the_token_to_the_origin(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (200, {}, b"zip-bytes")
    result = ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert result.status == 200 and result.bytes == 9 and (tmp_path / "x.zip").read_bytes() == b"zip-bytes"
    assert fake_ocl.requests[0]["headers"]["authorization"] == f"Token {TOKEN}"
    assert not list(tmp_path.glob("*.part"))


def test_download_never_overwrites(fake_ocl, tmp_path):
    (tmp_path / "x.zip").write_bytes(b"keep")
    with pytest.raises(ocl_http.OclHttpError, match="overwrite"):
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert (tmp_path / "x.zip").read_bytes() == b"keep" and fake_ocl.requests == []


def test_a_204_writes_nothing(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (204, {}, b"")
    result = ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert result.status == 204 and result.path is None and not list(tmp_path.iterdir())


def test_an_error_status_is_reported_with_its_code(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (403, {}, b'{"detail": "Authentication required"}')
    with pytest.raises(ocl_http.OclHttpError) as caught:
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", None, allow_insecure_localhost=True)
    assert caught.value.status == 403 and "Authentication required" in str(caught.value)


def test_a_redirect_is_followed_once_and_without_the_token(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (303, {"Location": "/storage/signed?sig=1"}, b"")
    fake_ocl.routes["/storage/signed?sig=1"] = (200, {}, b"from-storage")
    result = ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert (tmp_path / "x.zip").read_bytes() == b"from-storage" and result.redirected_to == "127.0.0.1"
    first, second = fake_ocl.requests
    assert first["headers"]["authorization"] == f"Token {TOKEN}"
    assert "authorization" not in second["headers"]


def test_a_second_redirect_is_refused(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (303, {"Location": "/a"}, b"")
    fake_ocl.routes["/a"] = (302, {"Location": "/b"}, b"")
    with pytest.raises(ocl_http.OclHttpError):
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert not (tmp_path / "x.zip").exists()


def test_a_redirect_to_plain_http_elsewhere_is_refused_and_the_token_is_not_sent_there(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (302, {"Location": "http://storage.example.org/file"}, b"")
    with pytest.raises(ocl_http.OclHttpError, match="https is required"):
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert len(fake_ocl.requests) == 1


def test_get_json_carries_the_status_on_failure(fake_ocl):
    with pytest.raises(ocl_http.OclHttpError) as caught:
        ocl_http.get_json(fake_ocl.url + "/missing/", TOKEN)
    assert caught.value.status == 404


def zipped(payload: bytes) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("export.json", payload)
    return buffer.getvalue()


def test_an_error_wrapped_in_a_zip_is_unwrapped_into_readable_text(fake_ocl, tmp_path):
    """OCL's zip renderer wraps error JSON in a ZIP (observed: 401 + application/zip on a local instance)."""
    body = zipped(b'{"detail":"Authentication credentials were not provided."}')
    fake_ocl.routes["/export/"] = (401, {"Content-Type": "application/zip"}, body)
    with pytest.raises(ocl_http.OclHttpError) as caught:
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", None, allow_insecure_localhost=True)
    message = str(caught.value)
    assert caught.value.status == 401 and "Authentication credentials were not provided." in message
    assert "PK" not in message


def test_a_binary_error_body_is_summarized_never_printed(fake_ocl, tmp_path):
    fake_ocl.routes["/export/"] = (500, {"Content-Type": "application/octet-stream"}, bytes(range(256)) * 4)
    with pytest.raises(ocl_http.OclHttpError) as caught:
        ocl_http.download(fake_ocl.url + "/export/", tmp_path / "x.zip", TOKEN, allow_insecure_localhost=True)
    assert "<1024 bytes of application/octet-stream>" in str(caught.value)
    assert all(char.isprintable() for char in str(caught.value))


def test_get_json_also_unwraps_a_zipped_error(fake_ocl):
    fake_ocl.routes["/thing/"] = (403, {"Content-Type": "application/zip"}, zipped(b'{"detail":"nope"}'))
    with pytest.raises(ocl_http.OclHttpError, match="nope"):
        ocl_http.get_json(fake_ocl.url + "/thing/", TOKEN)
