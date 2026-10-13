"""Import a terminology's ``pipeline`` package by its path, so two terminologies can coexist.

Every terminology keeps its code in ``terminologies/<authority>/<terminology>/pipeline/``. A plain
``import pipeline`` resolves through ``sys.modules["pipeline"]``, so the second terminology to be
imported in one process silently gets the first one's package (and ``import pipeline as x`` does not
help: the alias only renames the variable). Here the *path* is the identity instead:

    load("who/icd-10", "align")   # -> terminologies.icd.icd-10.pipeline.align
    load("who/icd-11", "cli")     # -> terminologies.icd.icd-11.pipeline.cli

``terminologies`` and its authority folders are namespace packages (no ``__init__.py``), and the
hyphen in a terminology folder is legal for ``importlib.import_module`` even though it cannot be
written in an ``import`` statement. Modules inside a pipeline use relative imports, so they never
mention the top-level name.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def package_name(terminology: str, module: str = "") -> str:
    """Dotted import name of ``terminologies/<terminology>/pipeline[/<module>]``."""
    parts = [segment for segment in terminology.strip("/").split("/") if segment]
    if not parts:
        raise ValueError("terminology must look like 'who/icd-10'")
    name = ".".join(["terminologies", *parts, "pipeline"])
    return f"{name}.{module}" if module else name


def load(terminology: str, module: str = "") -> ModuleType:
    """Import ``pipeline`` (or one of its modules) of the given terminology."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return importlib.import_module(package_name(terminology, module))
