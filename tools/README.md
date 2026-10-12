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

## `ocl_env.py`

The project-wide settings: `OCL_API_URL` and `OCL_API_TOKEN`. Order: variable already in the shell, then `--env-file` (or `$OCL_ENV_FILE`), then `.env` in the repository root. Only those two keys are read; the token is never printed; a file readable by other users produces a `chmod 600` warning. Tools call `ocl_env.bootstrap()` first and `ocl_env.describe_target()` to say which instance they will talk to. See [`.env.example`](../.env.example).

## `ocl_export_download.py`

Downloads the export of any Source version with `GET` only (`--owner`, `--source`, `--version`, default `HEAD`).

```bash
uv run python tools/ocl_export_download.py --env-file .env.production --owner WHO --source ICD-10-WHO \
    --out exports/prod/WHO_ICD-10-WHO_HEAD.zip
```

It never overwrites a file, writes `<name>.part` then renames, refuses anything that is not a ZIP holding `export.json`, and records the SHA-256, origin, and `token_sent` in `<name>.provenance.json`. A `204` means no export is ready: it stops and never asks the server to generate one. Exit codes: `0` saved, `2` refused or failed, `3` no export ready, `4` authentication required. The default output is `exports/<host>/<owner>_<source>_<version>.zip`, so production and local never share a name.

## `ocl_export.py`, `ocl_verify_update.py`

`ocl_export.py` reads an export (`export.json`, NDJSON, or a ZIP holding either) and refuses one that belongs to another owner or Source or repeats an id; the ICD-10 `--export` and the verifier share it.

`ocl_verify_update.py` is the offline verifier that turns a local run into evidence. `--mode update` compares the export taken BEFORE and AFTER an update with the artifact; `--mode create` compares the export after loading a new Source with the artifact. It reads files only, exits `0` only when every check passes, and writes a deterministic JSON report (file names and SHA-256, no absolute paths, no timestamp). With an empty artifact, update mode checks that a local replica equals the production export. The checks are listed in [`../tests/README.md`](../tests/README.md#what-ocl_verify_updatepy---mode-update-checks).

## `ocl_replica_seed.py`

Offline converter from an export to a **replica seed** for a local instance: `source.create.json` (the Source's configuration, with `id` taken from `short_code`), `replica_part_001..N.zip` plus the `.ndjson` each holds (concepts, then mappings, parents first; the cap, default 2 MB, is on the compressed zip), `post_import.patch.json` (the hierarchy root, to apply after the import), and `replica_manifest.json` (the export's SHA-256, counts, ordering and parent-URL statistics, every part's SHA-256). It makes no network call and uploads nothing; the upload is manual, parts in numeric order with one Queue ID. Parent URLs lose their version ids (they do not exist on another server) and no `Source`/`Organization` line is emitted. Check a seed against the export it came from with `ocl_verify_update.py --mode create --after <export> --artifact <seed dir>`.

## `ocl_artifacts.py`, `ocl_assets.py`, `ocl_pipeline_loader.py`

Shared by every terminology pipeline. `ocl_artifacts.py` writes ordered NDJSON parts, one-member ZIPs for each part, the complete bundle, a single-member `*.bundle.zip` for direct upload, and a `*.parts.zip` distribution wrapper with the nested part ZIPs and manifest. The outer `.parts.zip` is never uploaded; extract it and submit each inner part ZIP in numeric order. Only the bundle ZIP and audit are versioned; all generated parts and the parts wrapper are reproducible and ignored by Git. `ocl_assets.py` downloads a pinned public input and verifies its SHA-256 before keeping it. `ocl_pipeline_loader.py` imports a terminology's `pipeline` package by path (`load("icd/icd-10", "align")`), so two pipelines named `pipeline` can coexist in one process. None of them talks to OCL.

## `ocl_http.py`

Shared read-only HTTP guard: origin validation (production API by default, explicit opt-in for a custom HTTPS origin or localhost HTTP) and a no-redirect opener so a token never follows a redirect. Any tool that sends an OCL token goes through it. It is named `ocl_http` because a top-level `http` module would shadow the standard library.

See [`../skills/ocl-api/SKILL.md`](../skills/ocl-api/SKILL.md) for CLI and API operation guidance.
