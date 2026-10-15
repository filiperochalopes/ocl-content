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

[`source.json`](source.json) declares the Source properties, filters, display metadata, and hierarchy root. Each declared property must correspond to an `extras` key emitted by the concept builder, in addition to `concept_class`. Validate it locally, then read-only against the API (the tool prints the proposed PATCH and has no write mode):

```bash
uv run python tools/ocl_source_config.py --config terminologies/who/icd-11/source.json
uv run python tools/ocl_source_config.py --config terminologies/who/icd-11/source.json --check --include-hierarchy
```

### Source properties and concept extras

OCL distinguishes a Source-declared property from an arbitrary concept `extras` key. The latter can still appear under “customized” in the UI; registering it in `properties` gives it a declared display label/type and makes it available to Source-level presentation and filtering. The ICD-11 builder emits these eight extras, so all eight are declared below (the `concept_class` property is OCL concept metadata, not an extra):

| Property code / extra key | Type | Display | Meaning |
| --- | --- | --- | --- |
| `concept_class` | `code` | Concept class | OCL class: `Root`, `Chapter`, `Block`, or `Diagnosis`. |
| `ChapterNo` | `string` | Chapter | WHO chapter identifier as supplied, including extension chapter `X`; kept as text to preserve the identifier. |
| `DepthInKind` | `integer` | Depth in kind | Simple Tabulation depth within the same kind; for categories, depth 2 means its parent is a category and the parent's parent is not. |
| `IsResidual` | `code` | Residual | WHO residual-category flag, stored as the source's `True`/`False` code value; not inferred from the label. |
| `isLeaf` | `code` | Leaf | Whether the entity has no children in this tabulation, stored as `True`/`False`. This describes this release's tabulation, not all post-coordinated ICD-11 content. |
| `BlockId` | `string` | Block ID | Tabulation block identifier when supplied; absent values are omitted. |
| `BrowserLink` | `string` | BrowserLink (latest) | WHO browser URL, verbatim from the Simple Tabulation cell — a `latestrelease` link (it moves with WHO releases), not pinned to the imported release. |
| `Foundation URI` | `string` | Foundation URI | WHO ICD-11 Foundation entity URI from the Simple Tabulation. |
| `Linearization URI` | `string` | Linearization URI | WHO MMS linearization URI from the Simple Tabulation; identifies the MMS entity. |

`filters` currently defines two equality filters: `concept_class=Diagnosis` (exclude root/chapter/block concepts from the diagnosis-focused listing) and `isLeaf=True` (leaf concepts). `meta.display.concept_summary_properties` shows class, chapter and depth in the summary; `concept_filter_order` orders class, chapter and leaf controls. These display lists do not themselves add filter definitions. Empty extras are omitted from a concept, so a declared property need not be present on every resource.

`source.json` is the canonical desired configuration. After changing its `properties`, `filters` or `meta.display`, synchronize the local Source with the reviewed complete arrays and rebuild the concept search index: a Source PATCH alone does not refresh the index. Check the asynchronous indexing task to `SUCCESS`, then exercise representative property filters/searches. The local API flow is:

```text
POST /orgs/WHO/sources/ICD-11-WHO/concepts/indexes/  body: {}  -> 202, a Task
GET  /tasks/<task id>/                                         -> poll until SUCCESS
```

Property searches use the `extras.` namespace, for example `?extras.exact.isLeaf=True`; test the endpoint against the local API version and verify returned concept IDs/values, not only the Source read-back. Reindexing is asynchronous and may take several minutes for this 37k-concept Source. Do not reindex production without separate explicit authorization. The ICD-10 procedure and indexing semantics are also documented in [ICD-10's index guidance](../icd-10/README.md#rebuild-the-concept-index-after-changing-properties-or-filters).

The property `display` keys need an oclapi2 version that accepts them (see
[`../icd-10/README.md`](../icd-10/README.md#display-on-properties)). Applying the printed body is a
manual step; local rehearsal Source changes may be applied directly to the local API.

## Data sources and provenance

| Field | Value |
| --- | --- |
| Authority | WHO |
| Edition / release | ICD-11 MMS **2026-01**; the header cell reads `Version:2026 Jan 17 - 05:30 UTC` |
| Locale | `en` |
| Format | Tab-separated text inside a ZIP (the same table is also shipped as XLSX); UTF-8 with BOM |
| Retrieval URL | <https://icdcdn.who.int/static/releasefiles/2026-01/SimpleTabulation-ICD-11-MMS-en.zip> |
| SHA-256 | `f1356588f40953a83e3af2b662deab47c5e269f944d1ea4ed0cfeb2007c7cd39` (4,214,980 bytes) |
| Local path | `terminologies/who/icd-11/assets/who/2026-01/SimpleTabulation-ICD-11-MMS-en.zip` (not committed) |
| License / redistribution | Not verified here; the file is fetched on demand and kept out of Git |
| Alignment rule | Not applicable: this is the canonical content, not a translation |

The URL was checked: it returns exactly the file the sibling `ciel-scripts` repository keeps. The
2025-01 path with the same file name (the default in that repository's scripts) serves an **older
release** (`Version:2025 Jan 24`) with a different hash, so it does not reproduce this input.

```bash
uv run python terminologies/who/icd-11/pipeline/cli.py fetch-assets   # downloads and verifies the hash
```

## License and compliance

ICD-11 is published by the World Health Organization and is **© WHO 2020, licensed under the
Creative Commons Attribution-NoDerivatives 3.0 IGO licence (CC BY-ND 3.0 IGO)**. The licence, and
WHO's own clarifications of it, are in the *Digital Version Terms of Use and License Agreement*
(citation at the end of this section). The clauses that govern this workspace:

| Clause | What it requires | How this workspace complies |
| --- | --- | --- |
| 1.2.2 | Incorporating the classification into software is **not** an adaptation, provided the material is not renamed/remodelled, is attributed, and keeps its codes and URIs | The concept `id` is the WHO code, the name is the WHO title, and the Foundation/Linearization URIs are extras; the Source is attributed (below) |
| 1.2.3 | Storage and transmission must include the code, title and URI | `id` = code, `names[].name` = title, `extras["Foundation URI"]`/`extras["Linearization URI"]` = URIs, on every entity that has them |
| 1.2.4 | Mappings/crosswalks and translations are **not** covered and need a separate written agreement | This pipeline adds **no** mappings and **no** translations (see "Scope and compatibility") |
| 1.2.5 | Added data fields must be clearly identified as additions that do not originate from WHO | Every Source property description states its provenance; the WHO columns say so, and the non-WHO items (the synthetic root and `concept_class`) are flagged (below) |
| 1.2.1 | Must not be used to develop or promulgate a different standard | A faithful load of the WHO MMS Simple Tabulation, not a new standard |
| 1.3 | Published mentions must carry the WHO citation | Recorded below and in the Source `description` |

### What originates from WHO, and what this pipeline adds

All eight concept extras are columns of the WHO Simple Tabulation; none is invented here:

| Extra / property | Origin |
| --- | --- |
| `Foundation URI`, `Linearization URI` | WHO column, verbatim |
| `BlockId`, `ChapterNo`, `DepthInKind`, `IsResidual`, `isLeaf` | WHO column, verbatim |
| `BrowserLink` | WHO column, verbatim — the URL from the `=hyperlink(...)` cell kept as WHO wrote it (a `latestrelease` link, not pinned) |
| `concept_class` | **Not a WHO field**: OCL metadata derived from the WHO `ClassKind` column |

Two further items are **ours**, not WHO's, and must be recognisable as non-WHO additions: the
synthetic root concept `ICD-11-Root` (its name and description are written by this pipeline) and
the `Chapter-<No>` id fallback for a chapter row with no `Code`. The Source `description` and the
property `description`s in [`source.json`](source.json) state this.

The Source `description` above is applied **by hand**: the read-only `tools/ocl_source_config.py`
deliberately never patches the Source `name` or `description`, so set it on the Source when it is
created or updated (see the local-rehearsal step and [`tests/README.md`](../../../tests/README.md),
Flow B).

### The committed artifact

`bulkimport_icd11-who.bundle.zip` is versioned and carries WHO content (codes, titles, URIs).
Reproducing and redistributing the classification is permitted under 1.2.2/1.2.3 with the
attribution below and with codes and URIs kept intact — both hold in the artifact. The raw WHO
file is **not** committed (`assets/**/*.zip` is gitignored). Revisit this if the repository's own
licence or the WHO terms change.

### Citation

> International Classification of Diseases, Eleventh Revision (ICD-11), World Health Organization
> (WHO) 2019, <https://icd.who.int/browse11>. Licensed under the Creative Commons
> Attribution-NoDerivatives 3.0 IGO licence (CC BY-ND 3.0 IGO).

Vancouver (clauses 1.2.2–1.2.5 and 1.3 are on p. 2):

> World Health Organization. International Statistical Classification of Diseases and Related
> Health Problems (ICD), International Classification of Functioning, Disability and Health (ICF),
> International Classification of Health Interventions (ICHI): digital version terms of use and
> license agreement [Internet]. Geneva: World Health Organization; 2020 [cited 2026 Oct 12].
> Available from: <https://icd.who.int/en/docs/ICD11-license.pdf>

## Pipeline and output

```text
pipeline/
├── simple_tabulation.py   # reader: ids, parents, classes, release
├── build_bulkimport.py    # one line per entity, root first, hierarchy order checked
├── assets.py              # pinned input registry (mechanics shared via tools/ocl_assets.py)
└── cli.py                 # fetch-assets | build
```

```bash
uv run python terminologies/who/icd-11/pipeline/cli.py build
```

```text
output/
├── bulkimport_part_001.zip … NNN      # upload files, ≤ 2 MB compressed → NOT versioned
├── bulkimport_part_001.ndjson … NNN   # what each zip holds, ordered     → NOT versioned
├── bulkimport_bundle.ndjson                # every line in order                  → NOT versioned
├── bulkimport_icd11-who.bundle.zip         # one member: bulkimport_bundle.ndjson → versioned; direct upload
├── bulkimport_icd11-who.parts.zip          # inner part ZIPs + manifest            → NOT versioned; extract first
└── bulkimport_audit.json                   # provenance + counts + hashes          → versioned
```

The `.bundle.zip` is a single-member archive for one full import. The `.parts.zip` is only a distribution wrapper:
extract it and upload the inner `bulkimport_part_NNN.zip` files in numeric order, one Queue ID. Never upload the outer
`.parts.zip`; each inner part ZIP contains exactly one NDJSON file. Parts, nested upload ZIPs, the distribution ZIP,
and bundle NDJSON are reproducible and gitignored; only the bundle ZIP and audit are versioned.

Parts, bundle, manifest, and both hand-off ZIPs come from the shared `tools/ocl_artifacts.py`, so they behave exactly
as the ICD-10 ones: parts cut on resource boundaries in order, concatenation equals the bundle, a rebuild is byte-identical,
and the audit holds repo-relative paths and no timestamp.

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
  `ChapterNo`, `BrowserLink` (the URL from the `=hyperlink(...)` cell, verbatim — a `latestrelease`
  link, deliberately **not** pinned to the release), `isLeaf`; empty
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
skipped count are identical. One field is now deliberately different: the reference loader pins
`BrowserLink` to the release (`/browse/2026-01/…`), while this pipeline keeps the WHO cell verbatim
(`/browse/latestrelease/…`) — modifying WHO content is not permitted under CC BY-ND 3.0 IGO (see
[License and compliance](#license-and-compliance)), so the value is reproduced as-is.

## Uploading is manual

No script in this repository uploads a bulk import to OCL. A one-shot import uses
`bulkimport_icd11-who.bundle.zip` (one NDJSON member). For multipart import, extract
`bulkimport_icd11-who.parts.zip` and upload only the inner `bulkimport_part_NNN.zip` files **in
numeric order** through the OCL bulk-import form with one Queue ID. Never upload the outer
`.parts.zip`. The lines create complete concepts, so load them only into an **empty**
`WHO/ICD-11-WHO` Source — the importer would overwrite an existing concept's names and extras. Add
`en` to `supported_locales` and set the hierarchy root as described above before loading.

## Post-coordinated codes (additive layer)

A **separate, additive** layer on top of the base load above: indexed post-coordinated ICD-11 codes
(composite WHO codes such as `1A00&XN62R` or `5B81.Y/1A00`, each with its own Entity ID in the WHO
ICD-API search index but no row of its own in the Simple Tabulation). It never touches a concept the
base load already created — it only *adds* new `Diagnosis` concepts plus a `NARROWER-THAN` mapping
from each one to its first stem (per the owner's explicit decision: a mapping, not a
`parent_concept_urls` change — see "Design decisions" below).

```bash
uv run python terminologies/who/icd-11/pipeline/cli.py build-postcoordinated \
  --input <path to postcoord_index_items_full.csv> \
  --output-dir terminologies/who/icd-11/output/postcoordinated
```

### Input (external, not committed)

`--input` is the *full* CSV produced by the sibling `ciel-scripts` repository's
`list_postcoordinated_index_codes.py --full-csv` (invoked via `run_icd_api_postcoord_index_export.sh`),
which reads the protobuf search index a local `whoicd/icd-api` Docker container loads at boot and
hydrates each composite with one `/describe` and one Foundation-entity call. That generator is **not**
a WHO-published file — it is produced locally from a Docker container — so it is **not** copied into
this repository's `assets/`; the path is supplied on the command line at build time. Porting that
capture into a versioned, self-contained script in this pipeline (pulling the official `whoicd/icd-api`
image directly, rather than a personal compose file) is a planned follow-up, tracked but not yet built.

### Design decisions (owner-confirmed)

| Decision | Choice | Why |
| --- | --- | --- |
| Concept `id` | The raw WHO composite code, `&`/`/` kept as-is (not encoded, not normalized) | The owner's explicit choice: it is the real ICD-11 code |
| Stem relationship | `NARROWER-THAN` **mapping** to the first stem only — no `parent_concept_urls` | Matches the `ciel-scripts` reference loader's modeling; the base hierarchy built above is never touched |
| `concept_class` | `Diagnosis` (same class as the base stems) | Owner decision, plus `extras.is_postcoordinated` to distinguish it |
| Rejected codes (`describe_status=rejected_by_api`) | **Excluded by default**; pass `--include-rejected` to add them too | "Indexed" ≠ "valid" (the index still serves composites the API's own `/describe` value-set rules currently reject); the owner reviews them first via the HTML report below |
| Capture-script versioning | Deferred | Input stays external for now; porting the Docker-based capture into this pipeline is a tracked follow-up |

### A real, confirmed OCL bug — and the fix this builder applies

A concept id containing `/` creates fine, but a **raw, unencoded `/` in a mapping's
`from_concept_url` silently truncates `from_concept_code` at the first `/`** — a live instance of
[OpenConceptLab/ocl_issues#739](https://github.com/OpenConceptLab/ocl_issues/issues/739), confirmed
against this project's local OCL (2.3.208-dev) before this builder was written: creating a mapping
with `from_concept_url: ".../concepts/5B81.Y/1A00/"` resolved `from_concept_code` to `5B81.Y`,
silently dropping `/1A00`. **Fix**: percent-encode the slash as `%2F` (`quote(id, safe='')`, already
this repo's `concept_url()` convention) — confirmed to resolve `from_concept_code`/`from_concept_url`
correctly. `postcoord_mapping_line()` always goes through `concept_url()`, so every mapping this
builder emits is already encoded correctly.

A second, independent manifestation of the same underlying issue: fetching such a concept directly by
a *single* percent-encoded path (`GET .../concepts/5B81.Y%2F1A00/`) still 404s; only a *double*
encoding (`%252F`) in the request path reaches it. That only matters for a future per-concept
verification/GET tool, never for the bulk-import NDJSON lines this builder writes.

### Rejected-codes review

Before deciding whether to pass `--include-rejected`, review every indexed code's title source
(own WHO Foundation entity vs. composed-only), `describe_status`, Entity ID, and the local ICD-API
container's browse link, in one dense, filterable HTML (built to show several thousand rows at once):

```bash
uv run python terminologies/who/icd-11/pipeline/cli.py review \
  --input <path to postcoord_index_items_full.csv> \
  --output terminologies/who/icd-11/output/postcoord_index_review.html
# --rows rejected   -> only the describe_status=rejected_by_api rows
# --rows ok         -> only the describe_status=ok rows
```

### Properties and extras

Declared in [`source.json`](source.json), alongside the base load's properties: `is_postcoordinated`
(`True` on every concept this layer adds — not a WHO field), `Entity ID` (the composite Linearization
URI, WHO field verbatim), `StemCode` (derived from the code, not the CSV's own `stem_code` column —
see below), `Axes` (WHO `/describe` axis names), and `DescribeStatus` (`ok`/`rejected_by_api`, the WHO
API's own validation outcome as captured by this pipeline). `ExtensionCodes`, `ExtensionLabels`,
`DescribeError`, and `BrowseURL` extras are emitted but not yet declared as Source properties.

The first stem is always derived from the composite `code` string itself (everything before its
first `&` or `/`), never from the CSV's own `stem_code` column: that column comes from the `/describe`
hydration and is empty on every rejected row, while the composite code always carries its first
component regardless of hydration outcome.

### Current result (full capture, release 2026-01)

| | |
| --- | --- |
| Indexed composites | 4,227 (3,638 with an extension value, 657 with a second stem) |
| `describe_status=ok` | 3,559 → **built by default** |
| `describe_status=rejected_by_api` | 668 → excluded by default, reviewed separately |
| Unknown stems (not in the base Source) | 0, in both the default and `--include-rejected` run |
| Default build | 3,559 concepts + 3,559 mappings → 1 part, 176,748-byte bundle ZIP |

### Local rehearsal

This is the *additive update* case, not a fresh load: `WHO/ICD-11-WHO` already holds the base 37,053
concepts locally. Upload only into that already-populated Source (never an empty one — the base load's
own rehearsal is the "empty Source" case). After the manual import, confirm with read-only GETs that
`active_concepts`/`active_mappings` grew by exactly the counts above and that a sample mapping (e.g.
one whose `from_concept_url` contains `%2F`) resolves to the correct `from_concept_code`.

## Local rehearsal before production

This workspace is the *create a new Source* case. Create the empty `WHO/ICD-11-WHO` Source on a local OCL instance (the body to apply comes from `tools/ocl_source_config.py`), upload the parts by hand, download the resulting export, and run `tools/ocl_verify_update.py --mode create`: every artifact concept must exist with exactly its names, extras, and class, and the Source must hold no other concept. Commit the report under `evidence/`. See [`../../../tests/README.md`](../../../tests/README.md) (Flow B).

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
