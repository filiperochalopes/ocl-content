# OCL Content

Repository for terminology content, repeatable OCL pipeline tooling, and Source-level configuration.

## Current structure

```text
ocl-content/
├── terminologies/          # New, incremental home for terminology work
│   └── icd/icd-10/         # Pilot: Source configuration and operator guide
├── tools/                  # Shared Python helpers
├── skills/                 # Repository-local operational skills
├── tests/                  # Tests for shared helpers
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

See the terminology README for read-only checks and the deliberately guarded apply command.

## Shared tooling

- [`tools/ocl_source_config.py`](tools/ocl_source_config.py): validates, reads, and explicitly synchronizes Source-level properties, filters, display metadata, and—only when requested—hierarchy metadata.
- [`skills/ocl-api/SKILL.md`](skills/ocl-api/SKILL.md): operating guidance for the OCL CLI and the HTTP fallback used by pipeline tools.

## Development

The root tooling uses only the Python standard library at runtime. Tests require `pytest`:

```bash
python3 -m pytest
```

Do not commit API tokens, credentials, licensed releases, virtual environments, notebook checkpoints, caches, or generated full-load artifacts.
