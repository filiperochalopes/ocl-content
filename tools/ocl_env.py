"""Project-wide OCL settings: ``OCL_API_URL`` and ``OCL_API_TOKEN``, read from a ``.env`` file.

Every tool that talks to an OCL server reads the same two variables, so one place says which
instance the whole project points at. Resolution order, first match wins:

1. A variable already set in the shell (an explicit ``export`` always beats a file).
2. The file named by ``--env-file`` or, failing that, by ``$OCL_ENV_FILE``.
3. ``.env`` in the repository root, when it exists.

Keep one file per instance, for example ``.env.local`` and ``.env.production``, and choose with
``--env-file .env.local``. Only the two variables above are read; any other key in the file is
ignored and reported, so a stray line cannot inject configuration. The token is never printed:
:func:`describe_target` only says whether one is set. No dependency beyond the standard library.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_KEYS = ("OCL_API_URL", "OCL_API_TOKEN")
ENV_FILE_VARIABLE = "OCL_ENV_FILE"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
FLAG = "--env-file"


@dataclass
class EnvLoad:
    path: Path | None
    loaded: tuple[str, ...] = ()           # keys taken from the file
    kept_from_shell: tuple[str, ...] = ()  # keys the file also defined but the shell already set
    ignored: tuple[str, ...] = ()          # keys outside ALLOWED_KEYS
    warnings: list[str] = field(default_factory=list)


def parse_env_text(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines: ``export`` prefix, quotes, comments, and blank lines are handled."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in ("\"", "'") and value.find(value[0], 1) != -1:
            value = value[1:value.find(value[0], 1)]  # quoted: take what is inside; a trailing comment is dropped
        else:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


def resolve_env_file(explicit: Path | str | None = None, environ=None) -> Path | None:
    """Pick the env file: ``explicit``, then ``$OCL_ENV_FILE``, then the repository ``.env`` if present."""
    environ = os.environ if environ is None else environ
    chosen = explicit or environ.get(ENV_FILE_VARIABLE)
    if chosen:
        path = Path(chosen).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"env file not found: {path}")
        return path
    return DEFAULT_ENV_FILE if DEFAULT_ENV_FILE.is_file() else None


def load_env(explicit: Path | str | None = None, environ=None) -> EnvLoad:
    """Load the allowed variables into ``environ`` (default ``os.environ``) without overriding the shell."""
    environ = os.environ if environ is None else environ
    path = resolve_env_file(explicit, environ)
    if path is None:
        return EnvLoad(path=None)
    result = EnvLoad(path=path)
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        result.warnings.append(
            f"{path} is readable by other users; run `chmod 600 {path}` because it can hold a token"
        )
    loaded: list[str] = []
    kept: list[str] = []
    ignored: list[str] = []
    for key, value in parse_env_text(path.read_text(encoding="utf-8")).items():
        if key not in ALLOWED_KEYS:
            ignored.append(key)
        elif environ.get(key):
            kept.append(key)
        else:
            environ[key] = value
            loaded.append(key)
    result.loaded, result.kept_from_shell, result.ignored = tuple(loaded), tuple(kept), tuple(ignored)
    return result


def _flag_value(argv: list[str]) -> str | None:
    for index, argument in enumerate(argv):
        if argument == FLAG and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith(FLAG + "="):
            return argument.split("=", 1)[1]
    return None


def bootstrap(argv: list[str] | None = None, environ=None, *, stream=None) -> EnvLoad:
    """Call first in a tool's ``parse_args``: honor ``--env-file`` from ``argv`` and print any warning."""
    stream = stream or sys.stderr
    result = load_env(_flag_value(list(sys.argv[1:] if argv is None else argv)), environ)
    for warning in result.warnings:
        print(f"warning: {warning}", file=stream)
    return result


def describe_target(api_url: str, token: str | None, env: EnvLoad | None = None) -> str:
    """One line saying which instance a tool is about to talk to; it never contains the token."""
    source = f" (settings from {env.path.name})" if env and env.path else ""
    return f"OCL target: {api_url} | token: {'set' if token else 'NOT set'}{source}"
