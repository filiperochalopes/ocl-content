"""Project-wide OCL settings: OCL_API_URL and OCL_API_TOKEN from an env file."""

from __future__ import annotations

import os

import pytest

import ocl_env


def write(path, text, mode=0o600):
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_parse_handles_export_quotes_comments_and_blank_lines():
    parsed = ocl_env.parse_env_text(
        "# comment\n\nexport OCL_API_URL=http://api.ocl.localhost\nOCL_API_TOKEN=\"abc def\"\nOTHER='x' # trailing\nPLAIN=1 # note\n"
    )
    assert parsed == {"OCL_API_URL": "http://api.ocl.localhost", "OCL_API_TOKEN": "abc def", "OTHER": "x", "PLAIN": "1"}


def test_only_the_two_documented_variables_are_loaded(tmp_path):
    env = {}
    path = write(tmp_path / ".env", "OCL_API_URL=http://api.ocl.localhost\nOCL_API_TOKEN=t\nPATH=/evil\nFOO=bar\n")
    result = ocl_env.load_env(path, env)
    assert env == {"OCL_API_URL": "http://api.ocl.localhost", "OCL_API_TOKEN": "t"}
    assert result.loaded == ("OCL_API_URL", "OCL_API_TOKEN") and result.ignored == ("PATH", "FOO")


def test_the_shell_beats_the_file(tmp_path):
    env = {"OCL_API_URL": "https://api.openconceptlab.org"}
    path = write(tmp_path / ".env", "OCL_API_URL=http://api.ocl.localhost\nOCL_API_TOKEN=t\n")
    result = ocl_env.load_env(path, env)
    assert env["OCL_API_URL"] == "https://api.openconceptlab.org" and env["OCL_API_TOKEN"] == "t"
    assert result.kept_from_shell == ("OCL_API_URL",)


def test_env_file_variable_selects_a_profile_and_a_missing_one_fails(tmp_path):
    local = write(tmp_path / ".env.local", "OCL_API_URL=http://api.ocl.localhost\n")
    env = {"OCL_ENV_FILE": str(local)}
    ocl_env.load_env(None, env)
    assert env["OCL_API_URL"] == "http://api.ocl.localhost"
    with pytest.raises(FileNotFoundError):
        ocl_env.load_env(tmp_path / "missing", {})
    with pytest.raises(FileNotFoundError):
        ocl_env.load_env(None, {"OCL_ENV_FILE": str(tmp_path / "missing")})


def test_explicit_file_beats_the_environment_variable(tmp_path):
    a = write(tmp_path / "a", "OCL_API_URL=http://a.localhost\n")
    b = write(tmp_path / "b", "OCL_API_URL=http://b.localhost\n")
    env = {"OCL_ENV_FILE": str(b)}
    ocl_env.load_env(a, env)
    assert env["OCL_API_URL"] == "http://a.localhost"


def test_no_env_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ocl_env, "DEFAULT_ENV_FILE", tmp_path / "absent")
    assert ocl_env.load_env(None, {}).path is None


def test_a_group_readable_file_with_a_token_warns(tmp_path):
    result = ocl_env.load_env(write(tmp_path / ".env", "OCL_API_TOKEN=t\n", mode=0o644), {})
    assert any("chmod 600" in warning for warning in result.warnings)
    assert not ocl_env.load_env(write(tmp_path / ".env2", "OCL_API_TOKEN=t\n"), {}).warnings


def test_bootstrap_reads_the_flag_from_argv_in_both_forms(tmp_path, capsys):
    path = write(tmp_path / ".env.local", "OCL_API_URL=http://api.ocl.localhost\n")
    for argv in (["--env-file", str(path)], [f"--env-file={path}"]):
        env = {}
        assert ocl_env.bootstrap(argv, env).path == path and env["OCL_API_URL"] == "http://api.ocl.localhost"


def test_describe_target_never_contains_the_token(tmp_path):
    line = ocl_env.describe_target("http://api.ocl.localhost", "super-secret-token")
    assert "super-secret-token" not in line and "token: set" in line
    assert "NOT set" in ocl_env.describe_target("http://api.ocl.localhost", None)


def test_the_example_file_is_committed_without_a_real_token():
    from pathlib import Path

    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    values = ocl_env.parse_env_text(example)
    assert set(values) <= set(ocl_env.ALLOWED_KEYS)
    assert values.get("OCL_API_TOKEN", "") == ""
