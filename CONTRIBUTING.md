# Contributing

This repository manages terminology content, operational configuration, and repeatable tooling for Open Concept Lab (OCL).

## Compatibility and migration

- Existing top-level terminology folders are **legacy-compatible locations**. Do not move or delete them as part of an unrelated change.
- New work belongs under `terminologies/`; migrate legacy assets only in a dedicated, reviewed change that updates every documented path and validates the affected pipeline.
- Do not add new Jupyter notebooks for new workflows. Implement new repeatable workflows as tested Python modules or scripts.

## OCL safety

- Never commit API tokens, credentials, licensed source releases, or generated full-load artifacts.
- Local artifact generation and read-only OCL checks are allowed. Any OCL write, especially to production, requires explicit user authorization.
- Tools that mutate OCL must require an explicit opt-in flag, an explicit target, and a read-back verification.
- A Source configuration update must preserve unrelated `meta` entries and must not set a hierarchy root unless the root concept exists.

## Source configuration

Each new or migrated terminology Source should keep a reviewed `source.json` next to its documentation. It declares the Source-level `properties`, `filters`, and `meta.display` settings; it does not contain credentials.

Each terminology workspace also keeps one `README.md` following the template in [`terminologies/README.md`](terminologies/README.md). Whenever a workspace consumes another release — a canonical release, a national edition, or a set of translations — its README must document that source's provenance: authority, declared edition, locale, format, retrieval URL, SHA-256, local path, redistribution status, and the code-alignment rule.

Validate locally before any remote check:

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

Use `--check` for a read-only comparison. The tool prints the proposed PATCH body and has no write mode; applying it is a separate, manually authorized step.

## Terminology pipelines and output

- New repeatable terminology workflows are tested Python modules under `terminologies/<authority>/<terminology>/pipeline/`. Keep a chunk of code shared only when more than one pipeline genuinely uses it.
- A national edition is not a translation of a canonical release: align names by exact code, keep codes that exist only in the national edition out of scope, and record curated decisions in `review/` instead of encoding them as heuristics.
- Bulk-import artifacts belong in `terminologies/<authority>/<terminology>/output/`: ordered parts capped in size, the complete bundle, an alignment report, a machine-readable audit, and one zip holding parts + bundle + manifest. Only the **zip** and `bulkimport_audit.json` are versioned; parts and reports are byte-reproducible and stay out of Git.
- Review the proposal as a diff, not as a 12k-line NDJSON: `--dev-audit` writes the pretty-printed before/after pair (same IDs, same order, same fields) for pasting into a JSON-aware diff viewer. It is opt-in, never uploaded, and never versioned — the sibling `ciel-scripts` repository documents the same pair as *the canonical audit diff input*.
- A generated artifact must state whether it is upload-ready. Artifacts built from a committed snapshot are a draft; only a run that read every targeted concept from a Source export (`--export`) may be labelled upload-ready, and a missing concept must abort before anything is written. Artifacts and audits record repo-relative paths and no timestamps, so a rebuild is byte-identical.

## Uploading is manual

- Never add a script, helper, or skill that uploads a bulk import to OCL through the API, and never document one as an option. Generation produces local artifacts only.
- The hand-off is the archive: an operator extracts the parts and uploads them in numeric order through the OCL bulk-import form using one Queue ID. Record `"upload": {"mechanism": "manual", "api_upload": false}` in the audit and repeat the instruction in the manifest.

## Tests

Test-only dependencies are declared in `pyproject.toml` (`[dependency-groups] dev`), so the suite runs from the locked project environment instead of whichever `python3` happens to be first on `PATH`:

```bash
uv run python -m pytest            # root tooling + terminology pipelines
uv run python -m pytest tests/icd10
```

`uv run` always uses the project `.venv` and `uv.lock`, so a foreground shell and a background job resolve the same interpreter. A plain `python3 -m pytest` still works where pytest is already installed. Commit `uv.lock`; keep `.venv/` out of Git.
