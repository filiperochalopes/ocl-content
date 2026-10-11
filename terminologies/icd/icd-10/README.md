# ICD-10 WHO

Workspace for the WHO ICD-10 Source in Open Concept Lab (OCL): Source configuration, the
canonical-concept baseline, and the pipeline that proposes `pt_BR` and `fr` names from national
editions.

## Scope and compatibility

This folder is the configuration home for ICD-10 work and now also owns the name pipeline. It
does **not** move or replace the existing tracked import material in
[`../../../ICD-10 for OCL/`](../../../ICD-10%20for%20OCL/). That legacy directory remains the
authoritative repository location for the current CSV and ClaML assets until a dedicated
migration validates all downstream references.

The pipeline adds **names only**:

- it never creates a concept, never retires one, and never changes hierarchy, classes, or
  Source properties;
- it reads the canonical baseline for the concept IDs and hierarchy it must not alter;
- it proposes names for codes that exist in that baseline, in the locale of a national edition.

## OCL target

| Field | Value |
|---|---|
| Owner | `WHO` |
| Source | `ICD-10-WHO` |
| Synthetic root concept ID | `ICD-10` |
| Root concept name in legacy CSV | `ICD-10 Root Concept` |
| Hierarchy configuration | Declared for guarded restoration only; not applied by the name pipeline |
| Name locales proposed here | `pt_BR` (DATASUS CID-10), `fr` (ATIH CIM-10-FR) |

The existing CSV contains 12,587 concepts and parent links for 12,586 of them. It records
`ICD-10` as the synthetic root. The Source configuration declares `grouped-by` for this
classification hierarchy; changing this value requires a separate semantic review.

## Source configuration

[`source.json`](source.json) is declarative Source metadata. It contains:

- the OCL owner and Source IDs;
- five documented properties: `concept_class`, `hierarchy_level`, `Classification_Place`, `chapter_number`, and `Terminal_Node`;
- three configured filters with explicitly documented sample/default values;
- display order for concept summary properties and filters;
- the synthetic root identifier used only with `--include-hierarchy`.

The legacy fields `Classification_Place` (`N`/`T`) and `Terminal_Node` (`X`/`S`) are intentionally preserved as coded values. Their original definitions were not found in any documentation (WHO ClaML, DATASUS and this repository were checked), so they are described by what the HEAD export shows and are not recast as booleans or clinical assertions. `Classification_Place`: `N` = has children, `T` = no children, exact on all 12,586 concepts. `Terminal_Node` does **not** mean leaf: `S` marks 1,058 leaf codes whose WHO name is composed as `parent title: qualifier` (1,054 at the fourth character, 4 at the fifth, all present in the WHO canonical file); `X` is everything else, nodes included. The expansion of the letters is inferred, not documented.

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

The tool is **read-only by design**: it has no `--apply` and sends nothing to OCL. `--check` prints the
exact PATCH body for the managed fields — `properties`, `filters`, `meta.display`, and optionally
the hierarchy settings — and never includes the Source `name` or `description`, so it cannot rename
the live Source. Applying the printed body is a separate, manually authorized step in the OCL
environment you intend to change.

The tool obtains the token from `OCL_API_TOKEN` unless `--token` is supplied and never prints it.
It preserves existing unrelated remote `meta` entries in the proposal. Remote calls go through the
shared guard in [`tools/ocl_http.py`](../../../tools/ocl_http.py): the production API origin by
default (use `--allow-custom-api-url` only for an approved HTTPS non-production origin), and no
redirect is ever followed, so a token cannot leave the approved origin.

### `display` on properties

Each property in `source.json` carries a `display` label. This is a recent oclapi2 feature, already
used by `CIEL/CIEL`; an older deployment validates property keys against `code`, `uri`,
`description`, and `type` only and rejects the others (`Invalid keys in property`). Confirm that the
target environment runs a version that accepts `display` before applying the proposed body.

### Rebuild the concept index after changing properties or filters

Changing `properties`, `filters` or `meta.display` does not reindex the concepts. Filters and property
searches are served from the search index, so rebuild it to make a configuration change effective. (On the
rehearsal instance the index was rebuilt right after the PATCH and the counts below matched the export; the
state before the rebuild was not measured.)

```text
POST /orgs/WHO/sources/ICD-10-WHO/concepts/indexes/        body: {}        -> 202, a Task (state PENDING)
GET  /tasks/<task id>/                                                     -> wait for state SUCCESS
```

- It rebuilds the index of the **HEAD** concepts of this Source; use `/{version}/concepts/indexes/` for a released version. It is asynchronous: poll the task, do not assume.
- Like any write, it is manually authorized and **local first**. Run it against production only with explicit consent, after the production PATCH and its read-back.
- Verify with a property search, not with the Source read-back. Property filters on concepts use the `extras.` prefix (`?extras.exact.Terminal_Node=S`). Expected on the HEAD export of 2026-10-11 (12,587 concepts): `Classification_Place=T` 10,673; `Terminal_Node=S` 1,058; `Terminal_Node=X` 11,243; `chapter_number=1` 945.
- No tool in this repository calls this endpoint, in line with the read-only design of `ocl_source_config.py`.

### Hierarchy restoration

The Source already has a populated hierarchy; do **not** use the following command merely to document properties and filters. If a reviewed recovery procedure requires restoring the Source root, add `--include-hierarchy`: the helper first GETs `/concepts/ICD-10/` to verify the synthetic root exists, then includes `hierarchy_meaning` and `hierarchy_root_url` in the printed body.

```bash
python3 tools/ocl_source_config.py \
  --config terminologies/icd/icd-10/source.json \
  --check --include-hierarchy \
  --api-url "$OCL_API_URL"
```

## Validation expectations

Before any Source update:

1. Check that the target URL identifies the intended owner and Source.
2. Review the full proposed PATCH output, including complete `properties` and `filters` arrays.
3. Confirm the known legacy flags remain coded and unchanged.
4. For hierarchy work, confirm that `/concepts/ICD-10/` exists before applying the root setting (`--check --include-hierarchy` does this read).
5. After any manual write, read the Source back and compare it with the proposal.
6. **Rebuild the concept search index** (see "Rebuild the concept index" above) whenever `properties`, `filters` or `meta.display` changed. The PATCH only stores the configuration; filters and property searches are served from the search index, which is not updated by it.

## Data sources and provenance

Every input the name pipeline consumes, with the URL and hash needed to re-obtain it. The full
registry, including the note that DATASUS serves over plain HTTP, is in
[`assets/README.md`](assets/README.md); fetched data files are excluded from Git.

| Authority | Edition (as declared) | Locale | Format | Retrieval URL | SHA-256 | Role |
|---|---|---|---|---|---|---|
| WHO (via the tracked legacy CSV) | legacy load artifact, 10 Nov 2021 | `en` | CSV | [`../../../ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv`](../../../ICD-10%20for%20OCL/Production_Load_ICD-10_10Nov2021.csv) | recorded in `output/bulkimport_audit.json` | canonical baseline: IDs, hierarchy, English names, extras |
| DATASUS / Ministério da Saúde | CID-10 V2008 page; its XML declares `V2007` | `pt_BR` | semicolon CSV, ISO-8859-1 | http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip | `84f23809275575f751255048064bbb244b0de33fd5987ab98df0f98e5f5d2c95` | Brazilian CID-10 names (default) |
| DATASUS / Ministério da Saúde | same edition | `pt_BR` | DATASUS-specific XML with DTD entities, ISO-8859-1 | http://www2.datasus.gov.br/cid10/V2008/downloads/CID10XML.zip | `1f2f34076e50a28510aac7d2068003337aa05df1f4969571b46fd0dfa6de1385` | alternative Brazilian input; the adapter is selected from the file itself |
| ATIH | CIM-10-FR 2024 (`2024-01-01`) | `fr` | ClaML with `FM`/`OMS` label variants | https://www.atih.sante.fr/sites/default/files/content/documents/cim10fr2024syst_claml_20231215.zip | `6f7b631d2da9f932b85ed7397c7476169c869ba3992c8f862d2c918332a15c55` | French CIM-10 names |
| WHO | title declares `2019-covid-expanded`, date `2020-03-22`, Identifier `icd10_20210322` | `en` | ClaML | https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip | `344c571aa9aed3b9ad1c80261b7828c45cfb5fc0b1a5da64aecef354dff5b3d9` | canonical extraction and baseline verification |

The WHO release index is <https://icdcdn.who.int/icd10/index.html>: it lists every ICD-10 edition
available in ClaML/Meta, and the **2019 version (including COVID-19 updates)** is the newest one — it
is the release pinned above. The available editions, their relative links, and why this one was
chosen are recorded in [`assets/README.md`](assets/README.md#where-these-inputs-come-from-edition-discovery).

The French ZIP is byte-identical to the tracked legacy copy, so the `fr` adapter reads
[`../../../ICD-10 for OCL/cim10fr2024syst_claml_20231215/cim10fr2024syst_claml_20231215.xml`](../../../ICD-10%20for%20OCL/cim10fr2024syst_claml_20231215/cim10fr2024syst_claml_20231215.xml)
by default.

Redistribution terms for the DATASUS and WHO files were not established: do not commit a fetched
copy or redistribute it from this repository.

## What these files are

The DATASUS file is the **CID-10 brasileiro** and the ATIH file is the **CIM-10 français**:
national editions of ICD-10, not translations of the English release. They have their own codes,
chapter handling, and content, so a matching code is a candidate for a name review, never proof
that two entries mean the same thing.

### Alignment rules

| Rule | Behaviour |
|---|---|
| Code exists in the canonical baseline | Candidate name for the edition's locale |
| Code exists only in the national edition | `not-in-canonical`, excluded from the proposal |
| Label equals the canonical English name (case/space-insensitive) | `unchanged`, no name added |
| Two different labels for one code and locale | `duplicate-conflict`, refused as a group |
| Reviewed row in [`review/exclusions.csv`](review/exclusions.csv) | `excluded-by-curator`, held back with its reason |

Recorded normalizations, never silent: a DATASUS four-character subcategory (`A000`) becomes
`A00.0` with the original kept as `source_code`; a DATASUS chapter `NUMCAP` is used as a number
because the baseline numbers chapters `1`–`22`; a ClaML chapter roman numeral becomes that number
and is flagged `chapter-roman-normalized`; a preferred ClaML label containing a nested
`Reference` contributes only its own text and is flagged `inline-markup`. Inclusion, exclusion,
coding-hint and modifier content is never emitted as a name.

### Cases that require a curator decision

These are real rows in the current inputs, kept verbatim and surfaced by the alignment report:

- `A09` — DATASUS: “Diarréia e gastroenterite de origem infecciosa presumível”; the canonical
  English name also covers *unspecified* origin.
- `J09` — DATASUS names avian influenza while the canonical entry covers zoonotic **and
  pandemic** influenza. A row in `review/exclusions.csv` is the mechanism for holding it back.
- `U07.1` — the French edition carries both an `FM` label (“COVID-19”) and an `OMS` label
  (“COVID-19, virus identifié”); the pipeline selects `OMS`. There is no `pt_BR` name because
  the Brazilian table predates COVID-19.
- `U07.10` — a French national extension; it exists only outside the canonical release and is
  excluded, never truncated into `U07.1`.
- `A00.0` — the French preferred label is “À Vibrio cholerae 01, biovar cholerae”, a continuation
  of the parent’s wording; it is kept verbatim rather than composed into a standalone name.
- `A06.4` — the French label contains an asterisk reference (`K77.0`) that is not part of the
  name.

## Pipeline

```text
terminologies/icd/icd-10/
├── README.md
├── source.json
├── assets/README.md          # pinned sources, hashes, licence status
├── assets/datasus/2008/      # fetched inputs (Git-ignored)
├── pipeline/
│   ├── cli.py                # fetch-assets | canonical | build | compact
│   ├── assets.py             # pinned URLs + SHA-256 fetch/verify
│   ├── canonical.py          # canonical baseline loader (CSV or JSONL)
│   ├── model.py              # NameCandidate / AdapterResult
│   ├── xmlsafe.py            # shared, narrow ClaML reading
│   ├── adapters/
│   │   ├── datasus_csv.py    # CID-10 pt_BR tables (default)
│   │   ├── datasus_xml.py    # CID-10 pt_BR XML with DTD entities
│   │   ├── atih_claml.py     # CIM-10-FR fr ClaML
│   │   └── who_claml.py      # canonical extraction from the WHO ClaML
│   ├── align.py              # exact-code alignment and refusals
│   ├── export.py             # offline reader for a Source export
│   ├── build_bulkimport.py   # projection, size-capped parts, bundle, reports
│   └── (parts, bundle, manifest, and zip: shared in tools/ocl_artifacts.py)
├── review/exclusions.csv     # curated, reviewed hold-backs
└── output/                   # versioned: the zip and the audit
```

```bash
# 1. fetch and verify the pinned inputs (once per machine)
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset all

# 2. extract the canonical structure from the WHO ClaML and check the baseline against it
python3 terminologies/icd/icd-10/pipeline/cli.py canonical \
  --who-claml terminologies/icd/icd-10/assets/who/icd102019en/icd102019en.xml.zip \
  --compare "ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv"

# 3. build the parts, the bundle, and the zip from the committed baseline (draft)
python3 terminologies/icd/icd-10/pipeline/cli.py build

# 4. regenerate from a fresh export of WHO/ICD-10-WHO so the artifacts are safe to upload (offline)
python3 terminologies/icd/icd-10/pipeline/cli.py build --export <export.json or export.zip>

# other flags
#   --skip fr|pt_BR          build one locale only
#   --exclusions FILE        apply the curated hold-backs
#   --max-part-size SIZE     cap on each part's COMPRESSED upload zip (default 2mb)
#   --zip-method lzma        smaller archive for NDJSON (see below)
#   --no-archive             parts and bundle only; zip later with `compact`
#   --output-dir DIR         default: this folder's output/
#   --export FILE            Source export holding the current concepts (marks the artifact upload-ready)
```

### Output and what is versioned

```text
output/
├── bulkimport_part_001.zip         # upload file, ≤ 2 MB compressed → NOT versioned
├── bulkimport_part_001.ndjson      # what that zip holds, ordered   → NOT versioned
├── bulkimport_part_002.zip / .ndjson   # …
├── bulkimport_bundle.ndjson        # every line, in order → NOT versioned
├── alignment_report.csv            # review surface      → NOT versioned
├── bulkimport_audit.json           # provenance + counts + hashes → versioned
└── bulkimport_icd10-who.zip        # parts + bundle + manifest       → versioned
```

Parts are cut on resource boundaries **in the input order** and each is capped at
`--max-part-size` (default 2 MB **compressed**: the cap is on the size of each part's upload zip, so a large Source needs
few parts, not hundreds of raw 2 MB files); the zips are what you upload, in numeric order. Concatenating the NDJSON parts
in numeric order reproduces the bundle byte for byte, and a single resource larger than the cap is an error rather than a split. The zip
carries the parts, the whole bundle, and a `bulkimport_manifest.json` that lists the target, the
mode, whether the artifact is upload-ready, and every part's SHA-256.

Only the zip and the audit are committed: the parts, the bundle, the canonical extraction and the
alignment report are byte-reproducible from the inputs the audit records, and they would weigh
several megabytes in history on every run. `compact` (re)builds the zip from what is already on
disk — `--zip-method deflate` (default, maximum portability) or `lzma`, which is smaller for
NDJSON but not readable by every archive tool. On the current draft: 7,311,740 bytes of payload →
886,540 bytes with `deflate` (ratio 0.061) or ~727 KB with `lzma` (ratio 0.050).

### Uploading is manual

No script, skill, or pipeline in this repository uploads a bulk import to OCL, and none will be
added. The generated archive is the hand-off: extract the parts, then upload them **in numeric
order** through the OCL bulk-import form, reusing one Queue ID for all of them. The manifest
repeats that instruction, and the audit records `"upload": {"mechanism": "manual", "api_upload":
false}`. The pipeline makes **no network call at all**: `--export` reads a file from disk.

Each line carries the complete `names`, `descriptions`, and `extras` of the concept, plus
`type`, `id`, `concept_class`, `owner`, `owner_type`, and `source`. `datatype`, `external_id`,
`retired`, `parent_concept_urls`, and `mappings` are deliberately not sent: the Concept bulk
importer is not a PATCH, so an omitted `names`/`descriptions` collection is replaced by an empty
one, while OCL preserves omitted scalar values and hierarchy and treats an empty `mappings`
payload as a no-op. A translation is added only when its locale has no active name; an existing
name in that locale is never replaced and is reported instead.

The committed pair is the archive and the audit; the parts are rebuilt on demand and are never
committed.

### Draft versus upload-ready

`build` reads the committed baseline, which carries only the 2021 English names and the legacy
extras. The resulting parts are a **draft** (`"mode": "offline-baseline"`,
`"upload_ready": false`, with a warning recorded in the audit and in the archive manifest) and
must not be uploaded: they do not reflect live names, descriptions, or extras.

`build --export <file>` starts from the current state of every targeted concept in an export of
`WHO/ICD-10-WHO` instead of the baseline. Accepted inputs are the `export.json` of a Source version,
an NDJSON file of Concept resources, or a `.zip` holding either. The run stops and writes nothing
when the export belongs to another owner or Source, repeats an id, or lacks a targeted concept.
Only an export run records `"mode": "source-export"` and `"upload_ready": true`; the audit records
the export's repo-relative path, SHA-256, and how many concepts were requested and found.

An export is a snapshot, not live HEAD: take it shortly before uploading, because anything changed
in OCL after it was taken is overwritten by the bulk update. A file read from disk also needs no
token, no retry or backoff, and no credential guard — the roughly 12,500 sequential GETs the earlier
design needed are gone.

Neither mode touches the network or writes to OCL. Any upload is a separate, explicitly authorized,
manual action.

### Reproducibility and recorded paths

A rebuild from the same inputs is byte-identical, including the zip and `bulkimport_audit.json`:
neither carries a timestamp (when an artifact was produced is what Git history records), and every
path in the audit is relative to the repository root, so a machine's directory layout never leaks.
An input outside the repository is recorded by file name only; its SHA-256 identifies it.

### Locales, name type, and Source setup before upload

- **Locale tokens**: `pt_BR` and `fr` (plus the existing `en`). `pt_BR` is a deliberate choice: it
  is the token `CIEL/CIEL` uses, so names line up across Sources. OCL has both forms in use —
  `pt-BR` (IETF BCP 47, as `Regenstrief/LOINC` uses) and `pt_BR` (Java locale) are both listed on
  the `OCL/Locales` Portuguese concept — and a Source can only store one spelling per language, so
  `pt_BR` serves code and display alike. `fr` needs no region.
- **Name type**: every name the pipeline adds carries `name_type: "Fully Specified"`, the
  `OCL/NameTypes` standard value that the live English names already use (`A09` has one English
  name typed `Fully Specified`). CIEL uses a different set; this Source follows OCL's.
- **`supported_locales` is a manual step before the first upload.** `WHO/ICD-10-WHO` currently has
  `default_locale: en` and `supported_locales: [en]`. Add `pt_BR` and `fr` to `supported_locales`
  in the OCL environment you are loading, and keep `default_locale: en`. Neither `source.json` nor
  `tools/ocl_source_config.py` manages this field, and a bulk import into locales the Source does
  not list is the exact case to avoid.

## Canonical verification

`canonical` extracts the structure from the WHO ClaML release itself and compares it with the
baseline, so the baseline is checked against its source rather than trusted:

```bash
python3 terminologies/icd/icd-10/pipeline/cli.py canonical \
  --who-claml terminologies/icd/icd-10/assets/who/icd102019en/icd102019en.xml.zip \
  --out output/canonical_who_icd10.jsonl \
  --compare "ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv"
```

Run on the pinned release, the extraction produces 12,850 concepts from 11,539 `Class` elements
plus 1,312 modifier-derived codes (476 derived ids collide with an explicit class and are skipped,
one class has no preferred label), and the comparison with the 12,587-concept baseline reports:

| Measure | Result |
|---|---|
| IDs in both | 12,585 |
| Only in the WHO extraction | 265 (254 modifier-derived optional subdivisions, 11 range ids such as `C00-C97`) |
| Only in the baseline | 2 — the synthetic root `ICD-10` (legacy-only, expected) and `Z31.2` (unexplained, see below) |
| Concept-class mismatches | 0 |
| Name differences | 801, of which 782 are the baseline's `"<parent context>: <label>"` composition and 19 are other |

Two findings are worth keeping visible rather than smoothing over. The baseline composes some
names by prefixing the parent's wording (`Malignant neoplasm: External upper lip`), while the WHO
file carries the bare label (`External upper lip`) — the extractor returns the source label and
the comparison counts the composition separately. And `Z31.2` exists in the baseline but not as a
`Class` in this WHO file; its provenance is unresolved and it is listed here instead of being
reinterpreted.

Extras in an extraction are deliberately empty: the baseline's `hierarchy_level`,
`chapter_number`, `Classification_Place` and `Terminal_Node` come from the legacy import, and the
WHO `Meta` mortality codes are a different set. Use the extraction to verify structure, and the
baseline or a Source export to populate an artifact.

## Before/after dev audit (diff review)

The proposal can be reviewed as a diff instead of reading a 12,498-line NDJSON. `--dev-audit`
writes a pretty-printed pair, in the same run and with the same content as the payload:

```bash
uv run python terminologies/icd/icd-10/pipeline/cli.py build --dev-audit

# output/bulkimport_before.dev.audit.json   (6.4 MB — the 2021 baseline state)
# output/bulkimport_after.dev.audit.json    (10.5 MB — with the pt_BR/fr names added)
```

Both arrays carry exactly the same concept IDs, in the same order, with the same import-relevant
fields, so a JSON-aware diff viewer shows only the changed values. Open
<https://www.diffchecker.com/> (or any JSON diff), paste the two files, and read the proposal as
before/after per concept — `A09` gains a `fr` and a `pt_BR` name, `U07.10` is absent, and so on.

This mirrors the contract documented in the sibling `ciel-scripts` repository
(`CONTRIBUTING.md`, "OCL bulk-import artifacts"): `--before-json-output` is *the canonical audit
diff input*, produced in the same run as the payload, deterministically sorted, preserving the
collections the importer would otherwise replace. Neither file of the pair is uploaded or
versioned — the pair is a review aid, ignored by `terminologies/.gitignore`
(`*/*/output/*.dev.audit.json`).

## Local rehearsal before production

An update of `WHO/ICD-10-WHO` runs on a local OCL instance first: seed a replica from a production export, `build --export <local BEFORE export>`, upload the parts by hand, download the local AFTER export, and run `tools/ocl_verify_update.py --mode update` with `--audit bulkimport_audit.json`. The verifier checks that no existing name was removed or changed, that the only added names are the proposed `pt_BR`/`fr` ones typed `Fully Specified`, that descriptions, extras, class, and the retired flag did not move, and that every untargeted concept and the concept count are unchanged. Commit the report under `evidence/`. The flow, commands, and PR evidence are in [`../../../tests/README.md`](../../../tests/README.md).

## Review workflow

`output/alignment_report.csv` lists every candidate with its status and reason. When a reviewed
row must not be proposed, add it to [`review/exclusions.csv`](review/exclusions.csv):

```csv
code,locale,reason
J09,pt_BR,national label names avian influenza; meaning differs from the canonical entry
```

Then rebuild with `--exclusions review/exclusions.csv`. The decision, its reason, and the input
hashes are all recorded in `bulkimport_audit.json`.

## Tests

```bash
python3 -m pytest tests/icd10
```

They cover the DATASUS CSV schema and encoding handling, the DATASUS XML entities and structure,
the ClaML variant, chapter and modifier-expansion rules, the WHO extraction and baseline
verification, the alignment outcomes, the projection, the size-capped parts and their order, the
bundle and the versioned archive, idempotency and byte-for-byte determinism, the export versus
draft modes, the offline-only guarantee, and asset verification.

```bash
python3 -m pytest            # root tooling + terminology pipelines
python3 -m pytest tests/icd10
```

## Known limits

- **Locale tokens**: `pt_BR`, `fr`, and `en` are used as OCL locale values; see
  [Locales, name type, and Source setup before upload](#locales-name-type-and-source-setup-before-upload).
  Confirm the Source's `supported_locales` before the first upload.
- **Baseline name composition**: the 2021 baseline prefixes some names with their parent's wording
  (782 such cases). The name pipeline copies the baseline name as-is for the `en` locale, so keep
  the convention when regenerating the baseline from the WHO extraction.
- **`Z31.2`**: present in the baseline but absent from the WHO ClaML `Class` list. Unexplained;
  do not silently drop or redefine it.
- **Legacy flags with an inferred meaning**: `Classification_Place` (`N`/`T`) and
  `Terminal_Node` (`X`/`S`) are described by observed behavior (see Source configuration); their original definitions remain undocumented; the DATASUS `CLASSIF`, `RESTRSEXO`, and
  `CAUSAOBITO` columns (and the XML `duplaclassificacao`/`restricoes` elements) are different
  concepts and are not used as substitutes.
- **Optional subdivisions**: 265 codes exist in the WHO extraction but not in the baseline (254 of
  them optional modifier subdivisions). They are out of scope for the name proposal, which aligns
  strictly to the baseline.
- **Release choice**: the pinned WHO asset is the 2019 edition (including COVID-19 updates), the
  newest the WHO index offers — see [`assets/README.md`](assets/README.md#where-these-inputs-come-from-edition-discovery).
  A different edition means a different Source release decision, not a swap of the URL.
- **Production data anomaly (observed 2026-10-11 in the HEAD export, 12,587 concepts)**: `B07` has no parent (`/parents/` is empty on the live API) and two versions created minutes apart on 2026-09-17 with `update_comment: "error"`; its parent group `B00-B09` gained a version in the same window, and nine concepts (`B00`–`B06`, `B08`, `B09`) list two versions of that one parent. It looks like a failed operation, not an intended state. A replica copies it as is (`B07` stays orphaned) and records it in `replica_manifest.json`; it is not corrected here, and an update built on that snapshot inherits it.
- **No export from production has been run through the pipeline yet**; `--export` is covered by
  tests with synthetic exports only. Try the flow against a replica of `WHO/ICD-10-WHO` first.

## Related assets

- Legacy load CSV: [`../../../ICD-10 for OCL/Production_Load_ICD-10_10Nov2021.csv`](../../../ICD-10%20for%20OCL/Production_Load_ICD-10_10Nov2021.csv)
- French ClaML source asset: [`../../../ICD-10 for OCL/cim10fr2024syst_claml_20231215/`](../../../ICD-10%20for%20OCL/cim10fr2024syst_claml_20231215/)
- Shared OCL API instructions: [`../../../skills/ocl-api/SKILL.md`](../../../skills/ocl-api/SKILL.md)
- Terminology README template: [`../../README.md`](../../README.md)
