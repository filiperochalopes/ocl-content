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
