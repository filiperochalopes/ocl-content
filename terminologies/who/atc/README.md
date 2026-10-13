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
- **Out of scope**: DDD values, ATC/DDD Guidelines text, and a full leaf-level scrape of
  atcddd.fhi.no.
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
| NCBO BioPortal, UMLS2RDF ATC ontology | BioPortal submission 25; `owl:versionInfo "2025_02_10"`, `dcterms:source "UMLS 2025AB"` | Turtle | Exact ATC codes, preferred English names, `rdfs:subClassOf` hierarchy, UMLS CUIs and semantic types |
| OCL production `WHO/WHOATC` | HEAD concept-list snapshot, then candidate resources hydrated by individual GET | NDJSON | Exact current OCL IDs and lifecycle state for retirement audit only |
| WHO Collaborating Centre (`atcddd.fhi.no`) | cumulative/living page | HTML | Optional bounded structural cross-check only; **not** retirement or mapping evidence |

The BioPortal submission is immutable and hash-pinned in [`pipeline/assets.py`](pipeline/assets.py):
`af99bc159c72f0ef70c18065d68f61022bf6074efe65585eb5e826527dbcec4a`. Fetching needs a personal
`BIOPORTAL_API_KEY`, which is read only from the environment and never logged or committed. See
[`assets/README.md`](assets/README.md).

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
│   ├── build_bulkimport.py        # active concepts only
│   └── cli.py                     # fetch-assets | build | diff-export | build-retirements | crosscheck-chapters
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
extras are `ATC Level`, `CUI`, `Semantic Types`, and `Is_Drug_Class`.

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

## Optional atcddd.fhi.no structural cross-check

```bash
uv run python terminologies/who/atc/pipeline/cli.py crosscheck-chapters
```

This makes 15 GETs (one per level-1 chapter plus the index) and compares level-2 groups. It is a
bounded **structural** spot-check only: it does not determine retirements and it does not create a
mapping.

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
- The level-1/2 atcddd.fhi.no check is not a full crawl.
