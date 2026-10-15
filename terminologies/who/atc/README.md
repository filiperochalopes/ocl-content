# WHO ATC — Anatomical Therapeutic Chemical Classification

Workspace for the `WHO/WHOATC` Source in Open Concept Lab (OCL). It reads the NCBO BioPortal
UMLS2RDF export of the ATC ontology and produces a deterministic **active-content** bulk-import
artifact. Retirements are a separate, audited update; no `REPLACED BY` mapping is generated here.

## Scope and compatibility

- **Active classification build**: one concept per BioPortal ATC code (levels 1–5) plus a synthetic
  `Root`, with hierarchy from `rdfs:subClassOf`.
- **Retirement update**: only a concept that is **active in an immutable OCL snapshot** and **absent
  by exact code from the current BioPortal ontology** is proposed for retirement. Name similarity,
  the atcddd.fhi.no alterations page, and mappings are not lifecycle evidence.
- **No mappings**: the active artifact and retirement artifact contain no `Mapping` resource. The
  live Source currently has historical `REPLACED BY` mappings from the legacy load, but this pipeline
  neither creates nor updates them.
- **Out of scope**: DDD values and ATC/DDD Guidelines text. The WHOCC index crawl is read-only
  comparison evidence; it does not yet replace the active bulk-import builder's input contract.
- **Reference implementation**: `ciel-scripts/ocl_uploader_whoatc.py` is retained as read-only
  historical evidence. Its BioPortal Turtle parsing, level→class logic, and hierarchy were useful
  references; its alterations-based retirement/mapping logic is intentionally **not** replicated.

## OCL target

| Field | Value |
|---|---|
| Owner / Source | `WHO` / `WHOATC` |
| Synthetic root | `Root` (name `Root`, class `Root`) |
| Hierarchy meaning | `grouped-by` |
| Datatype | `None` on every concept |
| Mapping policy | No mapping resources generated |

On October 12, 2026, a read-only production check found 6,919 active concepts, a `Root` hierarchy
root, and 350 historical active `REPLACED BY` mappings. Those mappings are not accepted as evidence
for this refresh.

## Source configuration

[`source.json`](source.json) declares the Source properties, filters, display metadata, and synthetic
root. It declares `requires_mappings: false` because this pipeline does not create mappings.

```bash
uv run python tools/ocl_source_config.py --config terminologies/who/atc/source.json
uv run python tools/ocl_source_config.py --config terminologies/who/atc/source.json --check --include-hierarchy
```

`--check` is read-only; applying any printed Source PATCH is a separate, explicitly authorized action.

## Data sources and provenance

| Authority | Edition / release | Format | Role |
|---|---|---|---|
| NCBO BioPortal, UMLS2RDF ATC ontology | BioPortal submission 25; `owl:versionInfo "2025_02_10"`, `dcterms:source "UMLS 2025AB"` | Turtle | Pinned comparison baseline and legacy active-build input; not the proposed authority for current classification content |
| WHO Collaborating Centre (`atcddd.fhi.no`) | ATC/DDD Index 2026; public index last updated `2026-01-20` | HTML | Proposed authority for canonical codes, preferred names, hierarchy, and lifecycle; reproducibly crawled across levels 1–5 for the local comparison evidence |
| OCL production `WHO/WHOATC` | HEAD concept-list snapshot, then candidate resources hydrated by individual GET | NDJSON | Exact current OCL IDs and lifecycle state for retirement audit only |

The BioPortal submission is immutable and hash-pinned in [`pipeline/assets.py`](pipeline/assets.py):
`af99bc159c72f0ef70c18065d68f61022bf6074efe65585eb5e826527dbcec4a`. Fetching needs a personal
`BIOPORTAL_API_KEY`, which is read only from the environment and never logged or committed. See
[`assets/README.md`](assets/README.md).

## Upstream authority, licensing, and enrichment policy

**Status: proposed; the authority decision is pending (see `TBD.md`).** Nothing below authorizes an OCL update.

### Authority and target version

The WHO Collaborating Centre for Drug Statistics Methodology (WHOCC, Norwegian Institute of Public Health)
is the proposed authority for ATC codes, English names, hierarchy, lifecycle, and DDDs. The planned OCL
Source Version for the ATC/DDD Index 2026 edition is **`ATC-DDD-2026`** (valid from January 1, 2026; the
public index reports *Last updated: 2026-01-20*). The existing production versions use the UMLS-style
`2023AA`; that scheme names a UMLS release, which is not what the WHOCC publishes.

### What the WHOCC publishes and how this repository obtains it

- The complete ATC Index with DDDs and the Guidelines are **sold** by the WHOCC (maintainers report
  about 200 EUR at <https://orders.atcddd.fhi.no/home>; that site is an Angular single-page app whose
  text was not machine-readable here, so the price and sales terms must be confirmed there).
- The WHOCC also exposes a **public, searchable** index at <https://atcddd.fhi.no/atc_ddd_index/> and the
  public update workbook *ATC/DDD new and alterations 2026*
  (<https://orders.atcddd.fhi.no/api/files/download/?fileId=45>, SHA-256
  `6a58c3f5e96d13e2096377c4847714dee17e80694f31bf1228f1097c4335ee58`).
- **This repository never uses the purchased publication.** The only extraction channel is the public
  material above, read-only, with a descriptive `User-Agent` and a pause between requests. No copy of the
  crawled pages or of the workbook is redistributed from this repository.
- The WHOCC *User conditions* (March 2024) state, among other things: the Index and Guidelines are updated
  annually with versions valid from January 1; there must always be a reference to the version used;
  translations should be done by a national competent authority; and the Centre takes no responsibility for
  translations or for use in electronic health systems. They do not describe a redistribution licence, so
  the legal position of republishing the content in OCL is **not established here** and needs the owners'
  decision before any release. Any published Source must cite its origin in its description, for example:
  *WHO Collaborating Centre for Drug Statistics Methodology, ATC classification index with DDDs, 2026.
  Oslo, Norway 2026; obtained from the public ATC/DDD Index (https://atcddd.fhi.no/atc_ddd_index/).*

### Verified: the 2026 update workbook is already in the public index

Every row of the workbook was compared with the public index pages on 2026-10-14
([`evidence/atc2026_xlsx_vs_site.csv`](evidence/atc2026_xlsx_vs_site.csv), 160 checks, 157 pages): 96 new
5th-level codes, 3 new 3rd/4th-level names, 9 level-alteration checks (including the deleted temporary
`J07BX07` and the replacement `L01EX17` → `L01EP01`), 2 name alterations, 49 new DDDs and 1 altered DDD.
All 160 matched; the sheet `Ark1` is the Centre's internal Norwegian working sheet and was not compared.
This is a comparison of an update list with the site, not a validation of the whole classification.

### CUI and Semantic Types are not part of the classification

UMLS CUIs and Semantic Types are **not** official ATC content and are not WHOCC-published. They describe a
relationship between an ATC code and a UMLS concept, so they belong in **mappings** (to a UMLS source), not
as attributes on the concept. Temporary policy, every output: no `CUI`, no `Semantic Types` and no UMLS CUI note description is emitted (the
active build and `source.json` no longer carry them), and BioPortal (UMLS 2025AB) stays a legacy input.
`ATC Level` is not WHOCC content: it comes from the BioPortal `ATC_LEVEL` predicate and equals the code's level
(1–5). It is kept as an **integer** property and emitted as an integer. What the existing live concepts hold today
(`CUI`, `Semantic Types`, and the 127 `T001`–`T204` semantic-type concepts) is a separate, explicitly
audited decision; it is not made by this build.

## Pipeline

```text
terminologies/who/atc/
├── README.md
├── source.json
├── assets/README.md
├── pipeline/
│   ├── assets.py                  # pinned BioPortal submission + optional alterations fetch
│   ├── ttl_reader.py              # narrow stdlib-only Turtle reader
│   ├── align.py                   # exact-code comparison against an OCL snapshot
│   ├── retirements.py             # before/after retirement projection; never emits a Mapping
│   ├── atcddd_alterations.py      # optional cross-check reader; not lifecycle evidence
│   ├── atcddd_crosscheck.py       # bounded level-1/2 live structural cross-check
│   ├── atcddd_index.py            # all-level WHOCC Index crawler + comparison report writers
│   ├── build_bulkimport.py        # active concepts only
│   └── cli.py                     # fetch-assets | build | diff-export | build-retirements | crosscheck-chapters | crawl-index
└── output/
```

### Active-content build

```bash
# Fetch or verify the pinned BioPortal Turtle file. If it was downloaded manually,
# place it at assets/bioportal/submission-25/ATC.ttl and this verifies its hash.
export BIOPORTAL_API_KEY='…'
uv run python terminologies/who/atc/pipeline/cli.py fetch-assets

# Active ontology classes + Root only; offline; no OCL call; no retirements; no mappings.
uv run python terminologies/who/atc/pipeline/cli.py build
```

The active build maps ATC level 1→`Chapter`, 2→`Group`, 3–4→`Subgroup`, and 5→`Code`.
Level-1 classes hang under `Root`; every other code uses the upstream `rdfs:subClassOf` parent. Its
extras are `ATC Level` (integer) and `Is_Drug_Class`; UMLS fields are not emitted.

### Retirement decision and audited retirement artifact

First request the standard OCL Source export:

```bash
uv run python tools/ocl_export_download.py --env-file .env.production \
  --owner WHO --source WHOATC --out exports/prod/WHO_WHOATC_HEAD.zip
```

The OCL export endpoint returned **HTTP 204 on October 12, 2026**, meaning no ready HEAD export was
available. The downloader correctly stopped and did not ask the server to generate one. The allowed
fallback used for the current review is read-only and explicit:

```bash
# 1. Immutable listing snapshot: pagination-only GET /concepts/ (not a Source export)
uv run python tools/ocl_concept_snapshot_download.py --env-file .env.production \
  --owner WHO --source WHOATC \
  --out exports/prod/WHO_WHOATC_HEAD.listing.ndjson

# 2. Exact-code diff: active in snapshot and absent from upstream = candidate, nothing more
uv run python terminologies/who/atc/pipeline/cli.py diff-export \
  --export exports/prod/WHO_WHOATC_HEAD.listing.ndjson

# 3. Hydrate only those candidate concepts with individual read-only GETs, preserving current
#    names/descriptions/extras for the bulk update
uv run python tools/ocl_concept_hydrate.py --env-file .env.production \
  --owner WHO --source WHOATC \
  --ids-csv terminologies/who/atc/output/alignment_report.csv \
  --match-column status --match-value missing-from-ontology-retire-candidate \
  --out exports/prod/WHO_WHOATC_retire_candidates.ndjson

# 4. Offline audited retirement update: before/after JSON + NDJSON bundle; no mappings
uv run python terminologies/who/atc/pipeline/cli.py build-retirements \
  --snapshot exports/prod/WHO_WHOATC_retire_candidates.ndjson
```

The October 12, 2026 run found **127** active candidates. Every candidate ID is a UMLS semantic type
code (`T001`–`T204` with gaps), not an ATC code. The generated retirement artifact contains exactly
127 `Concept` lines whose only intended semantic change is `retired: false` → `true`; it contains zero
mappings. Its audit records the listing snapshot SHA-256 (`8c936399…aaa8ec`) and hydrated-candidate
SHA-256 (`c79ceb43…30e60d`).

The fallback is not equivalent to an official Source export. Re-run listing, diff, and hydration
immediately before manual import so the update reflects the live state at hand-off.

## Output

The active full-source build uses:

```text
output/
├── bulkimport_whoatc.bundle.zip
├── bulkimport_whoatc.parts.zip
└── bulkimport_audit.json
```

The audited retirement proposal uses:

```text
output/retirements/
├── bulkimport_whoatc_retirements.bundle.zip
├── bulkimport_whoatc_retirements.parts.zip
├── retirement_audit.json
├── retirements_before.dev.audit.json
└── retirements_after.dev.audit.json
```

Before any import, compare `retirements_before.dev.audit.json` and
`retirements_after.dev.audit.json` in a JSON-aware diff. They have the same 127 IDs, same order, and
same names/descriptions/extras; only the top-level `retired` field differs.

## Uploading is manual

No code in this repository uploads a bulk import. If the retirement update is explicitly approved:

1. upload `bulkimport_whoatc_retirements.bundle.zip`, or extract the `.parts.zip` and upload its
   inner one-member ZIPs in numeric order using one Queue ID;
2. enable **Update existing** in OCL's bulk-import form;
3. after import reaches a terminal success state, read back representative `T…` concepts and verify
   `retired: true`; verify that mapping count did not change.

No production write has been made by this pipeline.

## WHOCC ATC/DDD Index crawl and BioPortal comparison

```bash
# Read-only: crawl all 1–5 ATC levels from the live public WHOCC Index.
# The default is six concurrent requests with a 0.10-second scheduling pause.
uv run python terminologies/who/atc/pipeline/cli.py crawl-index
```

The command fetches the index root and every level-1 through level-4 page. It obtains levels 1–4
from the hierarchy links restricted to `showdescription=no`, and level 5 from the ATC table rows on
the level-4 pages; it does **not** request every individual level-5 page. A failed request aborts the
run, so a partial result cannot be presented as a full comparison. It writes these local evidence
artifacts:

```text
output/
├── whoatc_index_snapshot.json             # all WHOCC codes/names/parents, levels 1–5
├── whoatc_bioportal_vs_who_audit.json     # exact-code and label-difference rows
└── whoatc_bioportal_vs_who_audit.html     # standalone, searchable meeting view
```

The report records the WHOCC page's `Last updated` value, request count/errors, the pinned BioPortal
file SHA-256/version, and per-level totals. It compares exact identifiers and preferred labels after
case/whitespace normalisation only; punctuation remains meaningful. A difference is a review
candidate, never an automatic retirement, equivalence, or mapping decision.

`crosscheck-chapters` remains available as a quick 15-request level-1/2 structural spot-check:

```bash
uv run python terminologies/who/atc/pipeline/cli.py crosscheck-chapters
```

## Tests

```bash
uv run python -m pytest tests/atc
uv run python -m pytest
```

The tests cover narrow Turtle/HTML parsing, level→class and hierarchy projection, no-mapping active
builds, exact-code alignment, byte-identical artifacts, and the no-network build guard. The complete
repository suite additionally verifies isolation among all terminology `pipeline` packages.

## Known limits

- BioPortal can lag the official ATC/DDD Index. That affects freshness review but does not change the
  explicit retirement rule: candidate = active OCL code absent from the pinned upstream snapshot.
- The OCL HEAD export was unavailable (HTTP 204) on October 12, 2026. The current proposal therefore
  carries an explicit GET-listing + per-candidate-hydration fallback provenance, and must be refreshed
  before any import.
- No DDD/Guidelines content is represented.
- The full WHOCC crawl is comparison evidence, not yet the active bulk-import builder's upstream input.
  Moving that builder from the pinned BioPortal snapshot to the WHOCC snapshot requires a separately
  reviewed build-contract and release decision.
