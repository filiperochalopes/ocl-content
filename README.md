# OCL Content

Repository for terminology content, repeatable OCL pipeline tooling, and Source-level configuration.

## Current structure

```text
ocl-content/
├── terminologies/          # New, incremental home for terminology work
│   ├── README.md           # Terminology README template (sources, provenance, output)
│   ├── icd/icd-10/         # Pilot: Source configuration + name pipeline + output
│   └── icd/icd-11/         # Second terminology: base Source from the WHO Simple Tabulation
├── tools/                  # Shared Python helpers
├── skills/                 # Repository-local operational skills
├── tests/                  # Tests for shared helpers and terminology pipelines
├── LOINC/                  # Existing location; retained for compatibility
├── ICD-10 for OCL/         # Existing location; retained for compatibility
├── SNOMED-GPS/             # Existing location; retained for compatibility
├── WHO-ATC/                # Existing location; retained for compatibility
└── ...                     # Existing tools and examples; migrate deliberately
```

The legacy top-level folders remain valid while workflows are migrated incrementally. New work must not silently relocate or delete them.

## ICD-10 pilot

The ICD-10 pilot keeps declarative OCL Source metadata in
[`terminologies/icd/icd-10/source.json`](terminologies/icd/icd-10/source.json).
The configuration documents Source properties, filters, display order, and the expected synthetic hierarchy root without storing credentials.

Validate it locally:

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

The same workspace owns the translation pipeline that proposes `pt_BR` names from the Brazilian
CID-10 (DATASUS) and `fr` names from the French CIM-10-FR (ATIH) for codes that exist in the
canonical baseline, verifies that baseline against the WHO ClaML release, and writes ordered
size-capped bulk-import parts, the whole bundle, a single-member `*.bundle.zip`, and a `*.parts.zip`
distribution wrapper that contains the individual upload ZIPs:

```bash
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset all
python3 terminologies/icd/icd-10/pipeline/cli.py canonical --compare "ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv"
python3 terminologies/icd/icd-10/pipeline/cli.py build
```

Only the single-member bundle ZIP and the audit are committed. Upload one bundle ZIP for a full import, or extract `.parts.zip` and upload each inner part ZIP manually in numeric order through the OCL bulk-import form. Never upload the outer `.parts.zip` container. See the terminology README for the provenance table, alignment rules, canonical verification results, draft versus upload-ready distinction, and guarded Source commands.

## Shared tooling

- [`tools/ocl_source_config.py`](tools/ocl_source_config.py): validates and reads Source-level properties, filters, display metadata, and—only when requested—hierarchy metadata, and prints the proposed patch. It is read-only and has no write mode.
- [`tools/ocl_http.py`](tools/ocl_http.py), [`tools/ocl_artifacts.py`](tools/ocl_artifacts.py), [`tools/ocl_assets.py`](tools/ocl_assets.py), [`tools/ocl_pipeline_loader.py`](tools/ocl_pipeline_loader.py): the shared HTTP guard, bulk-import artifact writers, pinned-asset fetching, and by-path pipeline imports that every terminology pipeline uses.
- [`tools/ocl_env.py`](tools/ocl_env.py), [`tools/ocl_export_download.py`](tools/ocl_export_download.py), [`tools/ocl_export.py`](tools/ocl_export.py), [`tools/ocl_verify_update.py`](tools/ocl_verify_update.py), [`tools/ocl_replica_seed.py`](tools/ocl_replica_seed.py): the project-wide `OCL_API_URL`/`OCL_API_TOKEN` settings, the read-only export downloader, the shared export reader, the offline verifier that turns a local rehearsal into evidence, and the converter that turns a production export into a replica seed for the local instance.
- [`skills/ocl-api/SKILL.md`](skills/ocl-api/SKILL.md): operating guidance for the OCL CLI and the HTTP fallback used by pipeline tools.

## OCL settings and the local rehearsal

Every tool that talks to OCL reads two variables, `OCL_API_URL` and `OCL_API_TOKEN`, from the shell or from an env file (`.env`, or one file per instance chosen with `--env-file`). Copy [`.env.example`](.env.example) to `.env.local` (your local oclapi2, `http://api.ocl.localhost`) and `.env.production`; every `.env*` file except the example is ignored by Git, and the token is never printed.

Official content is updated, or a Source is created, **on a local OCL instance first**: seed a replica from a production export, build and apply the update by hand, then prove it with `tools/ocl_verify_update.py`. The flow, the commands, and the evidence a PR should carry are in [`tests/README.md`](tests/README.md).

## Development

The root tooling and the terminology pipelines use only the Python standard library at runtime. Test-only dependencies are declared in `pyproject.toml`, so the suite runs from the locked project environment:

```bash
uv run python -m pytest
```

`uv run` uses the project `.venv` and `uv.lock`, which keeps every shell — background jobs included — on one interpreter; `python3 -m pytest` also works where pytest is already installed. Commit `uv.lock` and keep `.venv/` ignored.

Do not commit API tokens, credentials, licensed releases, virtual environments, notebook checkpoints, caches, or generated full-load artifacts.
