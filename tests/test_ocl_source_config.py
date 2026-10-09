import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import ocl_source_config as subject


def config():
    return {
        "owner": "WHO",
        "source": "ICD-10-WHO",
        "name": "ICD-10 WHO Version",
        "description": "WHO International Classification of Diseases, Tenth Revision.",
        "content": {"requires_mappings": False, "has_hierarchy": True},
        "hierarchy": {"root_concept_id": "ICD-10", "meaning": "grouped-by"},
        "properties": [
            {
                "code": "concept_class",
                "type": "code",
                "display": "Concept class",
                "description": "The OCL concept class.",
            },
            {
                "code": "chapter_number",
                "type": "integer",
                "display": "Chapter",
                "description": "The ICD-10 chapter number.",
            },
        ],
        "filters": [
            {"code": "concept_class", "operator": ["="], "value": "Code"},
        ],
        "meta": {
            "display": {
                "concept_summary_properties": ["concept_class", "chapter_number"],
                "concept_filter_order": ["concept_class"],
            }
        },
    }


def test_validate_config_accepts_valid_source_configuration():
    subject.validate_config(config())


def test_validate_config_rejects_display_reference_to_unknown_property():
    invalid = config()
    invalid["meta"]["display"]["concept_summary_properties"].append("unknown")

    with pytest.raises(subject.ConfigError, match="unknown property"):
        subject.validate_config(invalid)


def test_build_patch_preserves_existing_meta_keys():
    current = {"meta": {"display": {"default_filter": "active"}, "custom": {"keep": True}}}

    payload = subject.build_patch(config(), current)

    assert payload["name"] == "ICD-10 WHO Version"
    assert payload["description"] == "WHO International Classification of Diseases, Tenth Revision."
    assert payload["properties"] == config()["properties"]
    assert payload["filters"] == config()["filters"]
    assert payload["meta"] == {
        "display": {
            "default_filter": "active",
            "concept_summary_properties": ["concept_class", "chapter_number"],
            "concept_filter_order": ["concept_class"],
        },
        "custom": {"keep": True},
    }


def test_build_patch_omits_hierarchy_unless_explicitly_requested():
    configured = config()
    configured["hierarchy"] = {"root_concept_id": "ICD-10", "meaning": "is-a"}

    payload = subject.build_patch(configured, {}, include_hierarchy=False)

    assert "hierarchy_root_url" not in payload
    assert "hierarchy_meaning" not in payload


def test_build_patch_generates_hierarchy_source_fields_when_requested():
    configured = config()
    configured["hierarchy"] = {"root_concept_id": "ICD-10", "meaning": "is-a"}

    payload = subject.build_patch(configured, {}, include_hierarchy=True)

    assert payload["hierarchy_meaning"] == "is-a"
    assert payload["hierarchy_root_url"] == "/orgs/WHO/sources/ICD-10-WHO/concepts/ICD-10/"




def test_validate_config_rejects_path_characters_in_ocl_identifiers():
    invalid = config()
    invalid["owner"] = "WHO/other"

    with pytest.raises(subject.ConfigError, match="owner must use OCL identifier characters"):
        subject.validate_config(invalid)


def test_validate_config_rejects_unmanaged_meta_keys():
    invalid = config()
    invalid["meta"]["dispaly"] = {"concept_summary_properties": []}

    with pytest.raises(subject.ConfigError, match="meta has unsupported keys"):
        subject.validate_config(invalid)


def test_validate_config_rejects_unhashable_filter_operator():
    invalid = config()
    invalid["filters"][0]["operator"] = [{"bad": "operator"}]

    with pytest.raises(subject.ConfigError, match="operator list"):
        subject.validate_config(invalid)


def test_validate_api_url_requires_https_unless_localhost_is_explicitly_allowed():
    with pytest.raises(subject.ConfigError, match="HTTPS"):
        subject.validate_api_url("http://api.openconceptlab.org")

    assert subject.validate_api_url("http://127.0.0.1:8000", allow_insecure_localhost=True) == "http://127.0.0.1:8000"


def test_main_blocks_apply_without_check_before_any_remote_request(monkeypatch, tmp_path):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    args = argparse.Namespace(
        config=path,
        api_url="https://api.openconceptlab.org",
        token="token",
        allow_custom_api_url=False,
        allow_insecure_localhost=False,
        check=False,
        apply=True,
        include_hierarchy=False,
        confirm_target="WHO/ICD-10-WHO",
    )
    monkeypatch.setattr(subject, "parse_args", lambda: args)
    monkeypatch.setattr(subject, "fetch_source", lambda *unused: pytest.fail("unexpected GET"))

    with pytest.raises(subject.ConfigError, match="requires --check"):
        subject.main()


def test_main_hierarchy_apply_reads_root_before_patch_and_reads_back(monkeypatch, tmp_path):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    args = argparse.Namespace(
        config=path,
        api_url="https://api.openconceptlab.org",
        token="token",
        allow_custom_api_url=False,
        allow_insecure_localhost=False,
        check=True,
        apply=True,
        include_hierarchy=True,
        confirm_target="WHO/ICD-10-WHO",
    )
    calls = []
    expected_patch = subject.build_patch(config(), {}, include_hierarchy=True)

    def fake_fetch(*unused):
        calls.append("get-source")
        return {} if calls.count("get-source") == 1 else expected_patch

    monkeypatch.setattr(subject, "parse_args", lambda: args)
    monkeypatch.setattr(subject, "fetch_source", fake_fetch)
    monkeypatch.setattr(subject, "verify_root", lambda *unused: calls.append("get-root"))
    monkeypatch.setattr(subject, "apply_patch", lambda *unused: calls.append("patch"))

    assert subject.main() == 0
    assert calls == ["get-source", "get-root", "patch", "get-source"]


def test_no_redirect_handler_rejects_redirects_before_a_token_can_follow_them():
    handler = subject.NoRedirect()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other.example/") is None
