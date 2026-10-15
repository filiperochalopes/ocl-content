# SNOMED GPS

Pipeline for the complete January 2026 SNOMED International Global Patient Set (GPS) in
`SNOMED-International/SNOMED-GPS`.

## Scope

The official January 2026 package contains **429,674** flat concept rows: 378,553 active and 51,121
inactive. This is intentionally much larger than the current 29,577-active-concept OCL Source: the
2026 implementation guide redefines GPS as all active International Edition concepts plus all concepts
inactive since 2012. The selected scope is therefore the complete official release, not the legacy
subset.

GPS is not SNOMED CT International Edition: it has no hierarchy, relationships, definitions,
mappings, semantic tags, translations, or historical associations. The pipeline must not infer any of
them.

## OCL target

| Field | Value |
|---|---|
| Owner / Source | `SNOMED-International` / `SNOMED-GPS` |
| Hierarchy | none |
| Mappings | none |
| Class / datatype | Trailing FSN semantic tag / `None` (for example, `Quilonia ethiopica (organism)` → `organism`; `Concept class` is the sole declared Source property, filter, and concept-summary column) |
| FSN | English non-preferred `Fully-Specified` name |
| US Preferred Term | English preferred untyped name (`name_type` omitted) |
| Lifecycle | TSV `Active=1` → `retired: false`; `Active=0` → `retired: true` |

The name projection matches representative existing concepts read from production on October 12, 2026.

## Provenance and licence

The manually acquired source is documented in [`assets/README.md`](assets/README.md). The January 2026
package's implementation guide and the [GPS product page](https://www.snomed.org/gps) state that the GPS
is distributed under CC BY-ND 4.0; the package `Readme.txt` separately carries copyright, College of
American Pathologists, and partner-rights notices. The current [online Technical Application page](https://docs.snomed.org/implementation-guides/gps-implementation-guide/technical-application)
shows CC BY 4.0 instead, so the official materials conflict; this configuration follows the exact
January 2026 package and product page and should be rechecked with SNOMED International before the next
release. The complete attribution, third-party rights note, trademark attribution, and licence link are
stored in [`source.json`](source.json) under `copyright`, separate from the content-scope `description`.
The raw ZIP is Git-ignored; `verify-asset` validates the pinned SHA-256 before every build.

## Commands

```bash
uv run python terminologies/snomed/gps/pipeline/cli.py verify-asset
uv run python terminologies/snomed/gps/pipeline/cli.py build
```

`build` is offline and deterministic. It writes parts, a full bundle, both hand-off ZIPs, and
`bulkimport_audit.json`; no code uploads anything to OCL.

The resulting artifact is a **full-source refresh**. It is not upload-ready until a fresh Source
snapshot is compared and a local OCL rehearsal is verified. If later approved, import manually with
**Update existing** enabled: the artifact updates existing legacy-subset records and creates the rest.

## Output

Only `bulkimport_snomed-gps.bundle.zip` and `bulkimport_audit.json` are versioned. Extract
`bulkimport_snomed-gps.parts.zip` and upload its inner part ZIPs in numeric order; never upload the
outer wrapper.

## Tests

```bash
uv run python -m pytest tests/gps
uv run python -m pytest
```
