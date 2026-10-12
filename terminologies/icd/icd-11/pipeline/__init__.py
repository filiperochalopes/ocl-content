"""ICD-11 base Source: WHO Simple Tabulation to OCL bulk-import artifacts.

The package reads the Simple Tabulation release, derives one concept per entity (chapter, block,
or category) plus the synthetic ``ICD-11-Root``, and writes versionable bulk-import NDJSON parts
with a machine-readable audit. It performs no OCL write and makes no network call at build time.
"""

import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)  # shared artifact/asset mechanics: tools/ocl_artifacts.py, tools/ocl_assets.py

from .simple_tabulation import Row, Tabulation, read  # noqa: E402

__all__ = ["Row", "Tabulation", "read"]
