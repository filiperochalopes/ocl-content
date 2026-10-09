# ICD-10 WHO

Pilot terminology workspace for the WHO ICD-10 Source in Open Concept Lab (OCL).

## Scope and compatibility

This folder is the new configuration home for ICD-10 work. It does **not** move or replace the existing tracked import material in [`../../../ICD-10 for OCL/`](../../../ICD-10%20for%20OCL/). That legacy directory remains the authoritative repository location for the current CSV and ClaML assets until a dedicated migration validates all downstream references.

The current pilot is limited to documenting and synchronizing Source-level properties, filters, and display metadata. It does not reload concepts, mappings, or hierarchy relationships.

## OCL target

| Field | Value |
|---|---|
| Owner | `WHO` |
| Source | `ICD-10-WHO` |
| Synthetic root concept ID | `ICD-10` |
| Root concept name in legacy CSV | `ICD-10 Root Concept` |
| Hierarchy configuration | Declared for guarded restoration only; do not apply it as part of the properties/filters update |

The existing CSV contains 12,587 concepts and parent links for 12,586 of them. It records `ICD-10` as the synthetic root. The Source configuration declares `grouped-by` for this classification hierarchy; changing this value requires a separate semantic review.

## Source configuration

[`source.json`](source.json) is declarative Source metadata. It contains:

- the OCL owner and Source IDs;
- five documented properties: `concept_class`, `hierarchy_level`, `Classification_Place`, `chapter_number`, and `Terminal_Node`;
- three configured filters with explicitly documented sample/default values;
- display order for concept summary properties and filters;
- the synthetic root identifier used only with `--include-hierarchy`.

The legacy fields `Classification_Place` (`N`/`T`) and `Terminal_Node` (`X`/`S`) are intentionally preserved as coded values. Their original business definitions were not found in the tracked artifact, so this configuration does not recast them as booleans or clinical assertions.

## Validate and synchronize

Local validation does not contact OCL:

```bash
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json
```

Read the current Source and print the proposed patch without changing OCL:

```bash
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json \
  --check \
  --api-url "$OCL_API_URL"
```

Apply **only** the properties, filters, and display configuration after explicit authorization for the intended OCL environment:

```bash
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json \
  --check --apply \
  --confirm-target WHO/ICD-10-WHO \
  --api-url "$OCL_API_URL"
```

The tool obtains the token from `OCL_API_TOKEN` unless `--token` is supplied. It never prints the token, preserves existing unrelated remote `meta` entries, and performs a GET verification after a successful PATCH. Remote calls default to the production API origin; use `--allow-custom-api-url` only for an approved HTTPS non-production origin.

### Hierarchy restoration

The Source already has a populated hierarchy; do **not** use the following command merely to document properties and filters. If a reviewed recovery procedure requires explicitly restoring the Source root, the helper verifies the synthetic root exists before patching the Source:

```bash
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json \
  --check --apply --include-hierarchy \
  --confirm-target WHO/ICD-10-WHO \
  --api-url "$OCL_API_URL"
```

## Validation expectations

Before any Source update:

1. Check that the target URL identifies the intended owner and Source.
2. Review the full proposed PATCH output, including complete `properties` and `filters` arrays.
3. Confirm the known legacy flags remain coded and unchanged.
4. For hierarchy work, confirm that `/concepts/ICD-10/` exists before applying the root setting.
5. After a write, require GET read-back verification from the helper and rebuild Source indexes only under the separately approved operational procedure.

## Related assets

- Legacy load CSV: [`../../../ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv`](../../../ICD-10%20for%20OCL/Production_Load_ICD-10_10Nov2021.csv)
- French ClaML source asset: [`../../../ICD-10 for OCL/cim10fr2024syst_claml_20231215/`](../../../ICD-10%20for%20OCL/cim10fr2024syst_claml_20231215/)
- Shared OCL API instructions: [`../../../skills/ocl-api/SKILL.md`](../../../skills/ocl-api/SKILL.md)
