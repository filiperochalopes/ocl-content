# Regenstrief LOINC — pt-BR translation audit

This workspace is deliberately **audit-only**. It does not create, update, retire, import, or upload OCL concepts, names, mappings, or Source configuration. It makes no network requests. The only OCL input is a complete, read-only export ZIP that was downloaded separately.

## Scope

`ptBR11LinguisticVariant.csv` in an official LOINC release is compared by exact `LOINC_NUM` against the `Regenstrief/LOINC/<version>` OCL export. The audit checks the Portuguese (Brazil) `Fully-Specified`, `Short`, and `Related` names. The release's seven translated term components (`COMPONENT`, `PROPERTY`, `TIME_ASPCT`, `SYSTEM`, `SCALE_TYP`, `METHOD_TYP`, `CLASS`) are joined with `:` for the `Fully-Specified` comparison, matching the representation observed in this OCL Source. `LONG_COMMON_NAME` and `LinguisticVariantDisplayName` are reported as release fields but are not treated as these three OCL name types. Empty source fields are reported as not provided, not as a failed OCL match.

Comparisons are exact-string checks, without normalization. They are evidence of data presence/label agreement only; they do not establish translation quality, clinical equivalence, or semantic correctness. Concepts are selected by `concept_class == "LOINC"` so same-code LOINC Part resources do not count as the observation-code concept. Retired concepts are included and explicitly marked in the row-level report.

## Run

First download the staging version export through the repository's read-only export tool. Do not ask OCL to generate an export from this command; if there is no export ready, generate it manually in the OCL UI, then download it.

```bash
uv run python tools/ocl_export_download.py \
  --env-file .env.staging \
  --owner Regenstrief --source LOINC --version 2.82 \
  --allow-custom-api-url \
  --out exports/api.staging.openconceptlab.org/Regenstrief_LOINC_2.82.zip

uv run python terminologies/regenstrief/loinc/pipeline/cli.py audit-ptbr \
  --release /Users/filipelopes/Downloads/Loinc_2.82.zip \
  --export exports/api.staging.openconceptlab.org/Regenstrief_LOINC_2.82.zip \
  --version 2.82
```

The audit validates the export's provenance sidecar, file hash, owner, Source, and version before comparing. It writes a compact JSON summary and a regenerable row-level CSV under `output/`. The release ZIP and OCL export remain external/local inputs and are not copied into this workspace or committed.

## Provenance and license

The audit records hashes for the official release archive, its ptBR11 CSV member, and the OCL export, plus the staging API origin and retrieval time from the export provenance sidecar. LOINC release materials and their license/attribution conditions remain governed by Regenstrief's terms; this workspace does not redistribute the source ZIP.
