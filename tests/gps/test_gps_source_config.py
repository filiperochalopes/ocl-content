"""SNOMED GPS Source-display configuration tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ocl_source_config as source_config


def test_gps_declares_concept_class_as_its_only_property_filter_and_summary_column():
    config = json.loads((ROOT / "terminologies" / "snomed" / "gps" / "source.json").read_text(encoding="utf-8"))

    source_config.validate_config(config)
    assert config["properties"] == [{
        "code": "concept_class",
        "type": "code",
        "display": "Concept class",
        "description": (
            "SNOMED semantic tag parsed from the trailing parenthesized tag of the source Fully Specified Name "
            "and emitted as the OCL concept class."
        ),
    }]
    assert [item["code"] for item in config["filters"]] == ["concept_class"]
    assert config["meta"]["display"] == {
        "concept_summary_properties": ["concept_class"],
        "concept_filter_order": ["concept_class"],
    }