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

Validate locally before any remote check:

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

Use `--check` for a read-only comparison. `--apply` is intentionally opt-in and requires an exact `--confirm-target OWNER/SOURCE` acknowledgement.

## Tests

Run the root tooling tests after changing a shared helper or a `source.json` contract:

```bash
python3 -m pytest
```
