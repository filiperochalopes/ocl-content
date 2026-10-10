# Shared Tools

## `ocl_source_config.py`

Validates and synchronizes declarative OCL Source metadata kept in a terminology `source.json` file.

It manages:

- `properties` definitions and their display labels/descriptions;
- `filters` and their configured order;
- `meta.display.concept_summary_properties` and `concept_filter_order`;
- optionally, `hierarchy_meaning` and `hierarchy_root_url`.

`name` and `description` in `source.json` are descriptive inputs and are not part of the proposed patch.

The tool is read-only. The default invocation is local-only; `--check` GETs the target Source and prints the proposed PATCH body, which never includes the Source `name` or `description`. There is no `--apply`: applying the body is a manual, separately authorized step. Property `display` keys require an oclapi2 version that accepts them (already live on CIEL).

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

## `ocl_artifacts.py`, `ocl_assets.py`, `ocl_pipeline_loader.py`

Shared by every terminology pipeline. `ocl_artifacts.py` writes the ordered, size-capped NDJSON parts, the whole bundle, the manifest, and the one zip, with fixed timestamps so a rebuild is byte-identical. `ocl_assets.py` downloads a pinned public input and verifies its SHA-256 before keeping it. `ocl_pipeline_loader.py` imports a terminology's `pipeline` package by path (`load("icd/icd-10", "align")`), so two pipelines named `pipeline` can coexist in one process. None of them talks to OCL.

## `ocl_http.py`

Shared read-only HTTP guard: origin validation (production API by default, explicit opt-in for a custom HTTPS origin or localhost HTTP) and a no-redirect opener so a token never follows a redirect. Any tool that sends an OCL token goes through it. It is named `ocl_http` because a top-level `http` module would shadow the standard library.

See [`../skills/ocl-api/SKILL.md`](../skills/ocl-api/SKILL.md) for CLI and API operation guidance.
