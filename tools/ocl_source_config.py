#!/usr/bin/env python3
"""Validate and synchronize declarative OCL Source configuration.

The tool manages Source-level metadata that is not part of concept bulk imports:
property definitions, configured filters, display metadata, and optionally the
hierarchy settings. It is read-only: it validates the configuration locally and,
with --check, GETs the live Source and prints the PATCH body that an operator
would apply by hand. It has no write mode and never changes the Source name or
description.

Property entries carry a ``display`` key. That is a newer oclapi2 feature (already
in use on CIEL); an older deployment rejects it, so confirm the target API version
before applying the printed body.

Use --include-hierarchy only when the configuration explicitly declares a
synthetic root that already exists in OCL. With --check the tool verifies that
concept before printing hierarchy_root_url.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocl_env  # noqa: E402
import ocl_http  # noqa: E402
from ocl_http import DEFAULT_API_URL, OCL_IDENTIFIER_RE, NoRedirect  # noqa: E402,F401

PROPERTY_TYPES = {"code", "Coding", "string", "integer", "boolean", "dateTime", "decimal"}
FILTER_OPERATORS = {
    "=", "is-a", "descendent-of", "is-not-a", "regex", "in", "not-in",
    "generalizes", "child-of", "descendent-leaf", "exists",
}


class ConfigError(ValueError):
    """Raised when a local Source configuration is structurally unsafe."""


def _require_identifier(config: dict[str, Any], key: str) -> str:
    value = _require_string(config, key)
    if not OCL_IDENTIFIER_RE.fullmatch(value):
        raise ConfigError(f"{key} must use OCL identifier characters: letters, numbers, '.', '_', '@', or '-'")
    return value


def source_path(config: dict[str, Any]) -> str:
    return f"/orgs/{quote(config['owner'], safe='')}/sources/{quote(config['source'], safe='')}/"


def root_concept_path(config: dict[str, Any]) -> str:
    hierarchy = config["hierarchy"]
    return f"{source_path(config)}concepts/{quote(hierarchy['root_concept_id'], safe='')}/"


def _require_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ConfigError("configuration must be a JSON object")
    _require_identifier(config, "owner")
    _require_identifier(config, "source")
    _require_string(config, "name")
    _require_string(config, "description")

    content = config.get("content")
    if not isinstance(content, dict):
        raise ConfigError("content must be an object")
    for key in ("requires_mappings", "has_hierarchy"):
        if not isinstance(content.get(key), bool):
            raise ConfigError(f"content.{key} must be a boolean")

    properties = config.get("properties")
    if not isinstance(properties, list) or not properties:
        raise ConfigError("properties must be a non-empty list")
    property_codes: set[str] = set()
    for index, prop in enumerate(properties):
        if not isinstance(prop, dict):
            raise ConfigError(f"property at index {index} must be an object")
        code = prop.get("code")
        if not isinstance(code, str) or not code:
            raise ConfigError(f"property at index {index} needs a code")
        if code in property_codes:
            raise ConfigError(f"duplicate property code: {code}")
        property_codes.add(code)
        unknown_keys = set(prop) - {"code", "uri", "description", "type", "display"}
        if unknown_keys:
            raise ConfigError(f"property {code} has unsupported keys: {sorted(unknown_keys)}")
        if prop.get("type", "string") not in PROPERTY_TYPES:
            raise ConfigError(f"property {code} has an unsupported type")
        if not isinstance(prop.get("display"), str) or not prop["display"].strip():
            raise ConfigError(f"property {code} needs a non-empty display")
        if not isinstance(prop.get("description"), str) or not prop["description"].strip():
            raise ConfigError(f"property {code} needs a non-empty description")

    filters = config.get("filters", [])
    if not isinstance(filters, list):
        raise ConfigError("filters must be a list")
    for index, filter_definition in enumerate(filters):
        if not isinstance(filter_definition, dict):
            raise ConfigError(f"filter at index {index} must be an object")
        allowed_filter_keys = {"code", "description", "operator", "value"}
        unknown_keys = set(filter_definition) - allowed_filter_keys
        if unknown_keys:
            raise ConfigError(f"filter at index {index} has unsupported keys: {sorted(unknown_keys)}")
        code = filter_definition.get("code")
        if code not in property_codes:
            raise ConfigError(f"filter at index {index} references unknown property: {code}")
        operators = filter_definition.get("operator")
        if not isinstance(operators, list) or not operators or not all(isinstance(operator, str) for operator in operators):
            raise ConfigError(f"filter {code} needs a non-empty operator list of strings")
        invalid_operators = set(operators) - FILTER_OPERATORS
        if invalid_operators:
            raise ConfigError(f"filter {code} has unsupported operators: {sorted(invalid_operators)}")
        if not isinstance(filter_definition.get("value"), str) or not filter_definition["value"]:
            raise ConfigError(f"filter {code} needs a non-empty value")
        if "description" in filter_definition and not isinstance(filter_definition["description"], str):
            raise ConfigError(f"filter {code} description must be a string")

    meta = config.get("meta", {})
    if not isinstance(meta, dict):
        raise ConfigError("meta must be an object")
    unknown_meta_keys = set(meta) - {"display"}
    if unknown_meta_keys:
        raise ConfigError(f"meta has unsupported keys: {sorted(unknown_meta_keys)}")
    display = meta.get("display", {})
    if not isinstance(display, dict):
        raise ConfigError("meta.display must be an object")
    unknown_display_keys = set(display) - {"concept_summary_properties", "concept_filter_order"}
    if unknown_display_keys:
        raise ConfigError(f"meta.display has unsupported keys: {sorted(unknown_display_keys)}")
    for setting in ("concept_summary_properties", "concept_filter_order"):
        values = display.get(setting, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigError(f"meta.display.{setting} must be a list of property codes")
        unknown_codes = set(values) - property_codes
        if unknown_codes:
            raise ConfigError(f"meta.display.{setting} references unknown property codes: {sorted(unknown_codes)}")

    hierarchy = config.get("hierarchy")
    if content["has_hierarchy"] and hierarchy is None:
        raise ConfigError("content.has_hierarchy is true but hierarchy is missing")
    if not content["has_hierarchy"] and hierarchy is not None:
        raise ConfigError("content.has_hierarchy is false but hierarchy is present")
    if hierarchy is not None:
        if not isinstance(hierarchy, dict):
            raise ConfigError("hierarchy must be an object")
        root_id = hierarchy.get("root_concept_id")
        meaning = hierarchy.get("meaning")
        if not isinstance(root_id, str) or not root_id or not OCL_IDENTIFIER_RE.fullmatch(root_id):
            raise ConfigError("hierarchy.root_concept_id must use OCL identifier characters")
        if not isinstance(meaning, str) or not meaning:
            raise ConfigError("hierarchy.meaning must be a non-empty string")


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    validate_config(config)
    return config


def deep_merge(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(existing)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def build_patch(
    config: dict[str, Any], current: dict[str, Any], *, include_hierarchy: bool = False
) -> dict[str, Any]:
    validate_config(config)
    current_meta_raw = current.get("meta")
    configured_meta_raw = config.get("meta")
    current_meta: dict[str, Any] = copy.deepcopy(current_meta_raw) if isinstance(current_meta_raw, dict) else {}
    configured_meta: dict[str, Any] = (
        copy.deepcopy(configured_meta_raw) if isinstance(configured_meta_raw, dict) else {}
    )
    # Managed fields only. name and description are descriptive inputs of the configuration and
    # are deliberately not part of the patch, so a run never renames the live Source.
    patch: dict[str, Any] = {
        "properties": config["properties"],
        "filters": config.get("filters", []),
        "meta": deep_merge(current_meta, configured_meta),
    }
    if include_hierarchy:
        hierarchy = config.get("hierarchy")
        if hierarchy is None:
            raise ConfigError("--include-hierarchy requires a hierarchy section in the configuration")
        patch["hierarchy_meaning"] = hierarchy["meaning"]
        patch["hierarchy_root_url"] = root_concept_path(config)
    return patch


def validate_api_url(
    api_url: str, *, allow_insecure_localhost: bool = False, allow_custom_api_url: bool = False
) -> str:
    try:
        return ocl_http.validate_api_url(
            api_url, allow_insecure_localhost=allow_insecure_localhost, allow_custom_api_url=allow_custom_api_url
        )
    except ocl_http.OclHttpError as exc:
        raise ConfigError(str(exc)) from None


def normalize_api_url(api_url: str) -> str:
    return api_url.rstrip("/")


def _get(url: str, token: str) -> dict[str, Any]:
    try:
        return ocl_http.get_json(url, token)
    except ocl_http.OclHttpError as exc:
        raise ConfigError(str(exc)) from None


def fetch_source(api_url: str, token: str, config: dict[str, Any]) -> dict[str, Any]:
    return _get(f"{normalize_api_url(api_url)}{source_path(config)}", token)


def verify_root(api_url: str, token: str, config: dict[str, Any]) -> None:
    _get(f"{normalize_api_url(api_url)}{root_concept_path(config)}", token)


def parse_args() -> argparse.Namespace:
    env = ocl_env.bootstrap()  # honors --env-file / OCL_ENV_FILE / .env before the defaults below are read
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="env file with OCL_API_URL / OCL_API_TOKEN (default: .env)")
    parser.add_argument("--config", type=Path, required=True, help="path to declarative source.json")
    parser.add_argument(
        "--api-url", default=os.getenv("OCL_API_URL", DEFAULT_API_URL),
        help=f"OCL API URL (default: OCL_API_URL or {DEFAULT_API_URL})",
    )
    parser.add_argument("--token", default=os.getenv("OCL_API_TOKEN"), help="OCL API token (default: OCL_API_TOKEN)")
    parser.add_argument(
        "--allow-custom-api-url", action="store_true",
        help="allow an HTTPS API URL other than the production API origin",
    )
    parser.add_argument(
        "--allow-insecure-localhost", action="store_true",
        help="allow HTTP only for localhost, 127.0.0.1, or ::1 development servers",
    )
    parser.add_argument("--check", action="store_true", help="read the target Source and print the proposed patch")
    parser.add_argument(
        "--include-hierarchy", action="store_true",
        help="also set hierarchy_root_url and hierarchy_meaning after verifying the configured root concept",
    )
    args = parser.parse_args()
    args.env = env
    return args


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.check and not args.token:
        raise ConfigError("--check requires --token or OCL_API_TOKEN")

    api_url = args.api_url
    if args.check:
        api_url = validate_api_url(
            args.api_url,
            allow_insecure_localhost=args.allow_insecure_localhost,
            allow_custom_api_url=args.allow_custom_api_url,
        )
        print(ocl_env.describe_target(api_url, args.token, getattr(args, "env", None)))
    current: dict[str, Any] = {}
    if args.check:
        current = fetch_source(api_url, args.token, config)
        if args.include_hierarchy:
            verify_root(api_url, args.token, config)
    patch = build_patch(config, current, include_hierarchy=args.include_hierarchy)

    print(f"target: {source_path(config)}")
    print("proposed PATCH (printed only; this tool has no write mode):")
    print(json.dumps(patch, indent=2, ensure_ascii=False, sort_keys=True))
    print("no OCL resource was modified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
