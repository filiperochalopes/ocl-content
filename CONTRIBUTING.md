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

## OCL environments and the local rehearsal

- The whole project uses two variables, `OCL_API_URL` and `OCL_API_TOKEN`, read by `tools/ocl_env.py` from the shell, `--env-file`/`$OCL_ENV_FILE`, or `.env`. Keep one env file per instance (`.env.local`, `.env.production`); every `.env*` file except `.env.example` is ignored. Never put a second spelling of these variables in a new tool, and never print the token.
- Every tool prints its target (`OCL target: <url> | token: set`) before the first request, and sends the token only through `tools/ocl_http.py`: the production origin by default, `*.localhost` over HTTP only with `--allow-insecure-localhost`, no redirect carrying the token.
- **Local first.** An update to an existing Source, and the creation of a new one, run against a local OCL instance before production: seed a replica from a read-only production export, build with `--export`, upload by hand, download the result, and verify it with `tools/ocl_verify_update.py` (`--mode update` or `--mode create`). The commit or PR carries the report. Flow, commands, and evidence are in [`tests/README.md`](tests/README.md).
- The rehearsal tests inside the suite simulate the importer; they are not evidence about a server. Only the verified local run is.
- Production remains read-only for every tool here. Downloading an export is a `GET`; a tool never asks the server to generate one, and `bulk_import_refactor.py --upload` from the sibling repository is not part of this flow.

## Source configuration

Each new or migrated terminology Source should keep a reviewed `source.json` next to its documentation. It declares the Source-level `properties`, `filters`, and `meta.display` settings; it does not contain credentials.

Each terminology workspace also keeps one `README.md` following the template in [`terminologies/README.md`](terminologies/README.md). Whenever a workspace consumes another release — a canonical release, a national edition, or a set of translations — its README must document that source's provenance: authority, declared edition, locale, format, retrieval URL, SHA-256, local path, redistribution status, and the code-alignment rule.

Validate locally before any remote check:

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

Use `--check` for a read-only comparison. The tool prints the proposed PATCH body and has no write mode; applying it is a separate, manually authorized step.

## Terminology pipelines and output

- New repeatable terminology workflows are tested Python modules under `terminologies/<authority>/<terminology>/pipeline/`. Keep a chunk of code shared only when more than one pipeline genuinely uses it: the part, bundle, manifest, and zip writers (`tools/ocl_artifacts.py`), the pinned-asset fetcher (`tools/ocl_assets.py`), and the by-path importer (`tools/ocl_pipeline_loader.py`) are shared by ICD-10 and ICD-11.
- A national edition is not a translation of a canonical release: align names by exact code, keep codes that exist only in the national edition out of scope, and record curated decisions in `review/` instead of encoding them as heuristics.
- Bulk-import artifacts belong in `terminologies/<authority>/<terminology>/output/`: ordered parts capped by compressed ZIP size, the complete bundle, a single-member `*.bundle.zip`, a `*.parts.zip` distribution wrapper, an alignment report, and a machine-readable audit. Only the **bundle ZIP** and `bulkimport_audit.json` are versioned; extract `.parts.zip` and upload its inner part ZIPs individually in numeric order, one Queue ID. Never upload the `.parts.zip` container itself.
- Review the proposal as a diff, not as a 12k-line NDJSON: `--dev-audit` writes the pretty-printed before/after pair (same IDs, same order, same fields) for pasting into a JSON-aware diff viewer. It is opt-in, never uploaded, and never versioned — the sibling `ciel-scripts` repository documents the same pair as *the canonical audit diff input*.
- A generated artifact must state whether it is upload-ready. Artifacts built from a committed snapshot are a draft; only a run that read every targeted concept from a Source export (`--export`) may be labelled upload-ready, and a missing concept must abort before anything is written. Artifacts and audits record repo-relative paths and no timestamps, so a rebuild is byte-identical.

## Pipeline imports

Every pipeline folder is called `pipeline`, so a top-level `import pipeline` resolves through `sys.modules["pipeline"]` and the second terminology in a process silently gets the first one's package; `import pipeline as x` does not help, because an alias only renames the variable (`tests/test_pipeline_isolation.py` proves both). Therefore:

- Inside a pipeline, import siblings **relatively** (`from .align import align`).
- Outside it (a `cli.py`, a test), import **by path** with `ocl_pipeline_loader.load("icd/icd-10", "align")`, which resolves to `terminologies.icd.icd-10.pipeline.align`. Never write `import pipeline` or `from pipeline import ...`; the isolation test fails if one appears.
- A `cli.py` must keep working as a script (`python3 terminologies/<authority>/<terminology>/pipeline/cli.py`) and as an imported module.

## Uploading is manual

- Never add a script, helper, or skill that uploads a bulk import to OCL through the API, and never document one as an option. Generation produces local artifacts only.
- The hand-off is either the single-member `*.bundle.zip` for one import, or the outer `*.parts.zip` as a distribution wrapper: extract it and upload only its inner one-member part ZIPs in numeric order through the OCL bulk-import form using one Queue ID. Never upload the outer parts wrapper. Record this distinction in the audit and manifest.

## Tests

Test-only dependencies are declared in `pyproject.toml` (`[dependency-groups] dev`), so the suite runs from the locked project environment instead of whichever `python3` happens to be first on `PATH`:

```bash
uv run python -m pytest            # root tooling + terminology pipelines
uv run python -m pytest tests/icd10
uv run python -m pytest tests/icd11
```

`uv run` always uses the project `.venv` and `uv.lock`, so a foreground shell and a background job resolve the same interpreter. A plain `python3 -m pytest` still works where pytest is already installed. Commit `uv.lock`; keep `.venv/` out of Git.
