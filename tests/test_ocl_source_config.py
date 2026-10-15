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
        "copyright": "© WHO. Licensed under CC BY-ND 3.0 IGO.",
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


def test_validate_config_accepts_flat_source_without_properties():
    flat = config()
    flat["content"] = {"requires_mappings": False, "has_hierarchy": False}
    del flat["hierarchy"]
    flat["properties"] = []
    flat["filters"] = []
    flat["meta"] = {"display": {"concept_summary_properties": [], "concept_filter_order": []}}

    subject.validate_config(flat)


def test_validate_config_rejects_empty_properties_for_hierarchical_source():
    invalid = config()
    invalid["properties"] = []

    with pytest.raises(subject.ConfigError, match="non-empty list"):
        subject.validate_config(invalid)


def test_validate_config_rejects_display_reference_to_unknown_property():
    invalid = config()
    invalid["meta"]["display"]["concept_summary_properties"].append("unknown")

    with pytest.raises(subject.ConfigError, match="unknown property"):
        subject.validate_config(invalid)


def test_validate_config_rejects_missing_copyright():
    invalid = config()
    del invalid["copyright"]

    with pytest.raises(subject.ConfigError, match="copyright"):
        subject.validate_config(invalid)


def test_validate_config_rejects_blank_copyright():
    invalid = config()
    invalid["copyright"] = "  "

    with pytest.raises(subject.ConfigError, match="copyright"):
        subject.validate_config(invalid)


def test_build_patch_preserves_existing_meta_keys():
    current = {"meta": {"display": {"default_filter": "active"}, "custom": {"keep": True}}}

    payload = subject.build_patch(config(), current)

    assert "name" not in payload and "description" not in payload  # never rename the live Source
    assert payload["copyright"] == config()["copyright"]
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


def test_build_patch_includes_configured_canonical_url():
    configured = config()
    configured["canonical_url"] = "http://hl7.org/fhir/sid/icd-10"

    payload = subject.build_patch(configured, {})

    assert payload["canonical_url"] == "http://hl7.org/fhir/sid/icd-10"


def test_validate_config_rejects_a_non_uri_canonical_url():
    configured = config()
    configured["canonical_url"] = "not a uri"

    with pytest.raises(subject.ConfigError, match="canonical_url must be an absolute HTTP or HTTPS URI"):
        subject.validate_config(configured)


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


def test_tool_has_no_write_mode():
    source = (ROOT / "tools" / "ocl_source_config.py").read_text(encoding="utf-8")
    assert "--apply" not in source and "apply_patch" not in source and "PATCH\"" not in source
    helper = (ROOT / "tools" / "ocl_http.py").read_text(encoding="utf-8")
    for verb in ("POST", "PUT", "DELETE", "PATCH"):
        assert f'method="{verb}"' not in helper


def test_main_check_reads_source_and_root_then_prints_without_writing(monkeypatch, tmp_path, capsys):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    args = argparse.Namespace(
        config=path,
        api_url="https://api.openconceptlab.org",
        token="token",
        allow_custom_api_url=False,
        allow_insecure_localhost=False,
        check=True,
        include_hierarchy=True,
    )
    calls = []
    monkeypatch.setattr(subject, "parse_args", lambda: args)
    monkeypatch.setattr(subject, "fetch_source", lambda *unused: calls.append("get-source") or {})
    monkeypatch.setattr(subject, "verify_root", lambda *unused: calls.append("get-root"))

    assert subject.main() == 0
    assert calls == ["get-source", "get-root"]
    assert "no OCL resource was modified" in capsys.readouterr().out


def test_main_check_requires_a_token(monkeypatch, tmp_path):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    args = argparse.Namespace(
        config=path, api_url="https://api.openconceptlab.org", token=None, allow_custom_api_url=False,
        allow_insecure_localhost=False, check=True, include_hierarchy=False,
    )
    monkeypatch.setattr(subject, "parse_args", lambda: args)
    with pytest.raises(subject.ConfigError, match="requires --token"):
        subject.main()


def test_custom_origin_needs_explicit_opt_in():
    with pytest.raises(subject.ConfigError, match="--allow-custom-api-url"):
        subject.validate_api_url("https://staging.example.org")
    assert subject.validate_api_url("https://staging.example.org", allow_custom_api_url=True) == "https://staging.example.org"


def test_no_redirect_handler_rejects_redirects_before_a_token_can_follow_them():
    handler = subject.NoRedirect()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other.example/") is None
