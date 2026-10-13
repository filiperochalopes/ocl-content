"""Two terminology pipelines must coexist in one process (the ``pipeline`` name collision).

Both pipelines live in a folder called ``pipeline``. A top-level ``import pipeline`` would resolve
through ``sys.modules["pipeline"]`` and hand the second terminology the first one's package, and
``import pipeline as x`` does not help because an alias only renames the variable. Importing by path
(``ocl_pipeline_loader.load``) gives every pipeline a unique module name instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from ocl_pipeline_loader import load, package_name

ROOT = Path(__file__).resolve().parents[1]
ICD10, ICD11 = "who/icd-10", "who/icd-11"


def test_each_terminology_gets_its_own_package():
    first, second = load(ICD10), load(ICD11)
    assert first is not second
    assert first.__name__ == "terminologies.who.icd-10.pipeline"
    assert second.__name__ == "terminologies.who.icd-11.pipeline"
    assert Path(first.__file__).parents[1].name == "icd-10"
    assert Path(second.__file__).parents[1].name == "icd-11"


def test_modules_with_the_same_role_do_not_shadow_each_other():
    assets10, assets11 = load(ICD10, "assets"), load(ICD11, "assets")
    assert assets10 is not assets11
    assert set(assets10.ASSETS) != set(assets11.ASSETS)
    assert load(ICD10, "cli") is not load(ICD11, "cli")


def test_a_top_level_pipeline_package_is_never_registered():
    load(ICD10, "cli")
    load(ICD11, "cli")
    assert "pipeline" not in sys.modules


def test_an_alias_import_would_not_have_worked():
    """Documents why the loader exists: the alias is the very same module object."""
    import importlib

    for name in ("pipeline", "terminologies_probe"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(ROOT / "terminologies/who/icd-10"))
    try:
        first = importlib.import_module("pipeline")
        sys.path.insert(0, str(ROOT / "terminologies/who/icd-11"))
        second = importlib.import_module("pipeline")
        assert first is second and "icd-10" in first.__file__
    finally:
        for entry in (str(ROOT / "terminologies/who/icd-10"), str(ROOT / "terminologies/who/icd-11")):
            if entry in sys.path:
                sys.path.remove(entry)
        for name in [m for m in sys.modules if m == "pipeline" or m.startswith("pipeline.")]:
            del sys.modules[name]


def test_package_name_rejects_an_empty_terminology():
    with pytest.raises(ValueError):
        package_name("")


def test_no_pipeline_code_imports_a_top_level_pipeline():
    pattern = re.compile(r"^\s*(from pipeline[\s.]|import pipeline\b)", re.MULTILINE)
    offenders = [
        str(path.relative_to(ROOT))
        for path in [*ROOT.glob("terminologies/**/pipeline/**/*.py"), *ROOT.glob("tests/**/*.py")]
        if path.name != Path(__file__).name and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
