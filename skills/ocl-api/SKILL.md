---
name: ocl-api
description: Use OCL CLI or safe HTTP fallback for OCL tasks.
version: 0.1.0
author: Filipe Lopes, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [OCL, API, CLI, Terminology, Validation]
    related_skills: []
---

# OCL API Operations

Use this skill for pipeline checks, validation, and read-only OCL operations. It does not apply Source changes: the repository helper only prints the proposed body, and any write is a separate, manually authorized step. Prefer the OCL CLI for operations it supports; use the repository Python helper when the CLI is absent or when Source properties, filters, or display metadata must be synchronized.

## When to Use

- A pipeline needs to identify an OCL server, authenticated user, Source, task, or bulk import.
- A terminology needs to validate or synchronize Source-level properties, filters, display settings, or a hierarchy root.
- The `ocl` CLI is unavailable or does not expose the required Source field.

Do not use this skill to infer a terminology's Source ID, synthetic root, hierarchy meaning, or property semantics. Those are terminology-owned configuration inputs.

## Prerequisites

The project reads two variables, `OCL_API_URL` and `OCL_API_TOKEN`, from the shell or from an env file (`.env`, or `--env-file .env.local` / `.env.production`, one file per instance; see `.env.example`). Never commit them and never print the token. A shell export wins over a file:

```bash
export OCL_API_URL="https://api.openconceptlab.org"   # or http://api.ocl.localhost for the local instance
export OCL_API_TOKEN="<token>"
```

Production requires a token even to read. A local `http://api.ocl.localhost` needs `--allow-insecure-localhost`. Read exports with `tools/ocl_export_download.py` (GET only; never triggers generation) and prove an update or a new Source with `tools/ocl_verify_update.py`; the local-first flow is in `tests/README.md`.

Check for the CLI by running `ocl --help` in a shell. The CLI handles common repository, concept, mapping, import, and task operations. Its current `ocl repo update` interface does not expose Source `properties`, `filters`, or `meta.display`; use `tools/ocl_source_config.py` for those fields.

## Procedure

1. **Identify the environment.** Run `ocl --show-request whoami` when the CLI is available. Record the server URL and authenticated identity before an OCL operation is proposed.
2. **Use a read-only path first.** Use `ocl repo get <owner> <source> --type source` for supported Source reads, or run `python3 tools/ocl_source_config.py --config <path>` for local-only validation.
3. **Choose the HTTP fallback when required.** For declarative Source metadata, run `python3 tools/ocl_source_config.py --config <path> --check --api-url "$OCL_API_URL"`. It performs a GET and prints the exact PATCH body (managed fields only; never the Source name or description) without mutating OCL. Property `display` keys need an oclapi2 version that accepts them.
4. **Validate hierarchy before mutation.** A hierarchy-bearing pipeline must create or import its synthetic root concept before configuring `hierarchy_root_url`. Pass `--include-hierarchy` only when the terminology configuration contains a reviewed root ID and hierarchy meaning.
5. **Bind the API origin deliberately.** Remote calls default to `https://api.openconceptlab.org`. Pass `--allow-custom-api-url` for an approved HTTPS staging/self-hosted origin, or `--allow-insecure-localhost` only for a local HTTP server.
6. **Writes are manual.** The helper has no `--apply`. Review the printed body, then apply it yourself in the intended environment only with explicit authorization, and read the Source back to confirm every managed field.
7. **Check asynchronous work.** Use `ocl task` or the API task endpoint to wait for bulk-import or hierarchy-amendment tasks before calling the load complete.

## Quick Reference

```bash
# CLI available: inspect authentication and Source metadata
ocl --show-request whoami
ocl repo get WHO ICD-10-WHO --type source

# CLI-independent local validation
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json

# CLI-independent read-only API comparison
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json \
  --check --api-url "$OCL_API_URL"
```

## Pitfalls

- Do not put a token in a script, notebook, `source.json`, shell history, or committed artifact.
- The helper sends a token only to the production API origin by default, through the shared guard in `tools/ocl_http.py`. A custom origin or insecure localhost requires an explicit command-line opt-in; redirects are rejected so tokens cannot follow a server-controlled redirect.
- `properties` and `filters` are complete Source arrays. Review their entire proposed replacement before applying a patch.
- The helper preserves unrelated `meta` keys but manages the configured `meta.display` keys.
- `hierarchy_root_url` is Source-level metadata. It is not a substitute for importing concepts or applying parent links.
- Do not infer the meaning of coded legacy extras such as `X`, `S`, `N`, or `T` without source evidence.

## Verification

- Local validation exits successfully before any API call.
- A read-only run prints the exact target Source path and PATCH payload.
- After any manual apply, a GET read-back matches every managed field of the printed body.
- `--include-hierarchy` with `--check` confirms that the configured root concept exists before printing the hierarchy fields.
