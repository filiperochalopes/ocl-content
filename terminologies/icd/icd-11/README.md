# ICD-11 (WHO) — base Source from the Simple Tabulation

Second terminology workspace in this repository, built from the WHO ICD-11 MMS *Simple Tabulation*.
It exists to exercise the shared pipeline mechanics (`tools/ocl_artifacts.py`, `tools/ocl_assets.py`)
with a second, structurally different terminology, and to expose anything that only works while a
single terminology exists.

## Scope and compatibility

- **Covers**: one concept per Simple Tabulation entity (chapter, block, category) plus the synthetic
  `ICD-11-Root`, with the hierarchy that the tabulation itself states.
- **Does not cover**: post-coordinated codes, mappings, translations, descriptions (except the
  root's), and the `Source` record. The Source is expected to exist already.
- **Reference implementation**: the sibling `ciel-scripts` repository (`ocl_uploader_icd11.py`) is the
  audited loader this pipeline mirrors. It is read-only reference; nothing here imports it.
- **Status**: a *test terminology*. Nothing here was verified against OCL, so the artifacts are marked
  `upload_ready: false`.

## OCL target

| Field | Value |
| --- | --- |
| Owner / Source | `WHO` / `ICD-11-WHO` |
| Root concept | `ICD-11-Root` (fully specified name `ICD-11 Root`, class `Root`) |
| Hierarchy meaning | `grouped-by` |

## Source configuration

[`source.json`](source.json) declares the Source properties, filters, display metadata, and the
hierarchy root. Every property maps to an `extras` key the pipeline writes. Validate it locally, then
read-only against the API (the tool prints the proposed PATCH and has no write mode):

```bash
uv run python tools/ocl_source_config.py --config terminologies/icd/icd-11/source.json
uv run python tools/ocl_source_config.py --config terminologies/icd/icd-11/source.json --check --include-hierarchy
```

The property `display` keys need an oclapi2 version that accepts them (see
[`../icd-10/README.md`](../icd-10/README.md#display-on-properties)). Applying the printed body is a
manual, separately authorized step.

## Data sources and provenance

| Field | Value |
| --- | --- |
| Authority | WHO |
| Edition / release | ICD-11 MMS **2026-01**; the header cell reads `Version:2026 Jan 17 - 05:30 UTC` |
| Locale | `en` |
| Format | Tab-separated text inside a ZIP (the same table is also shipped as XLSX); UTF-8 with BOM |
| Retrieval URL | <https://icdcdn.who.int/static/releasefiles/2026-01/SimpleTabulation-ICD-11-MMS-en.zip> |
| SHA-256 | `f1356588f40953a83e3af2b662deab47c5e269f944d1ea4ed0cfeb2007c7cd39` (4,214,980 bytes) |
| Local path | `terminologies/icd/icd-11/assets/who/2026-01/SimpleTabulation-ICD-11-MMS-en.zip` (not committed) |
| License / redistribution | Not verified here; the file is fetched on demand and kept out of Git |
| Alignment rule | Not applicable: this is the canonical content, not a translation |

The URL was checked: it returns exactly the file the sibling `ciel-scripts` repository keeps. The
2025-01 path with the same file name (the default in that repository's scripts) serves an **older
release** (`Version:2025 Jan 24`) with a different hash, so it does not reproduce this input.

```bash
uv run python terminologies/icd/icd-11/pipeline/cli.py fetch-assets   # downloads and verifies the hash
```

## Pipeline and output

```text
pipeline/
├── simple_tabulation.py   # reader: ids, parents, classes, release
├── build_bulkimport.py    # one line per entity, root first, hierarchy order checked
├── assets.py              # pinned input registry (mechanics shared via tools/ocl_assets.py)
└── cli.py                 # fetch-assets | build
```

```bash
uv run python terminologies/icd/icd-11/pipeline/cli.py build
```

```text
output/
├── bulkimport_part_001.ndjson … 012   # ≤ 2 MB, ordered      → NOT versioned
├── bulkimport_bundle.ndjson           # every line, in order → NOT versioned
├── bulkimport_audit.json              # provenance + counts + hashes → versioned
└── bulkimport_icd11-who.zip           # parts + bundle + manifest    → versioned
```

Parts, bundle, manifest, and zip come from the shared `tools/ocl_artifacts.py`, so they behave exactly
as the ICD-10 ones: parts cut on resource boundaries in order, concatenation equals the bundle, a
rebuild is byte-identical, and the audit holds repo-relative paths and no timestamp.

### Rules the reader applies

- **ID** (first match): `Code`, then `BlockId`, then `Chapter-<ChapterNo>` for a chapter, then the
  suffix after `/mms/` in the linearization URI. A row with none of these (blank lines, editorial
  notes) is skipped and counted.
- **Class**: `chapter` → `Chapter`, `block` → `Block`, `category` → `Diagnosis`.
- **Name**: the `Title` without its leading `- ` depth markers; one English `Fully Specified` name.
- **Parent**: a chapter hangs under `ICD-11-Root`; a sub-code (`1A03.0`) under its stem (`1A03`);
  otherwise the deepest `Grouping` column; otherwise the `Parent` Foundation URI resolved to a
  concept; otherwise the chapter. Parents are resolved over the whole file, so a parent that appears
  after its child is still found. (The reference loader resolves in one pass.)
- **Order**: file order, root first. The build refuses a parent that is missing or later than its
  child, because OCL imports lines in order.
- **Extras**: `Foundation URI`, `Linearization URI`, `BlockId`, `DepthInKind`, `IsResidual`,
  `ChapterNo`, `BrowserLink` (pinned to the release instead of `latestrelease`), `isLeaf`; empty
  values are dropped.

### Current result

| | |
| --- | --- |
| Entities read | 37,052 (28 chapters, 1,360 blocks, 35,664 categories) |
| Rows skipped | 100, all without a supported identifier |
| Duplicate ids / missing parents / parents after children | 0 / 0 / 0 |
| Lines written | 37,053 (the entities plus the root) |
| Parts / bundle / zip | 12 / 23,254,874 bytes / 2,312,569 bytes (`deflate`) |

**Cross-check**: the 37,052 rows were compared with the reference loader's own parse of the XLSX
(same release, `release_tag=2026-01`). All twelve compared fields (id, title, class kind, parent,
both URIs, block id, depth, residual flag, chapter, browser link, leaf flag), the order, and the
skipped count are identical.

## Uploading is manual

No script in this repository uploads a bulk import to OCL. The hand-off is the archive: extract the
parts and upload them **in numeric order** through the OCL bulk-import form with one Queue ID. The
lines create complete concepts, so load them only into an **empty** `WHO/ICD-11-WHO` Source — the
importer would overwrite an existing concept's names and extras. Add `en` to `supported_locales` and
set the hierarchy root as described above before loading.

## Tests

```bash
uv run python -m pytest tests/icd11
```

They cover the id fallbacks, the parent rules (including a parent defined after its child), titles,
classes, the release and browser link, skipped lines, the projection, escaping, the order guard, the
size-capped parts and their concatenation, byte-identical rebuilds, the absence of absolute paths,
the pinned asset, and the absence of any network surface in the build.

## Related assets

- Pinned input registry: [`pipeline/assets.py`](pipeline/assets.py), provenance in
  [`assets/README.md`](assets/README.md)
- ICD-10 workspace, the first user of the shared mechanics: [`../icd-10/README.md`](../icd-10/README.md)
