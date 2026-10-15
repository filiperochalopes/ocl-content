# ICD-10-CM FY27

Pipeline for `US-NCHS/ICD-10-CM`, built from the CMS/NCHS FY27 release effective **October 1,
2026 through September 30, 2027**.

## Scope

FY27 changed the archive layout relative to FY26: the `table-and-index` ZIP no longer includes the
fixed-width order file. The pipeline combines two official FY27 assets:

1. `icd10cm-tabular_-2027.xml` in `icd10cm-table-and-index-2027.zip` supplies chapters, sections,
   explicit diagnosis nesting, titles, and seventh-character rules.
2. `icd10cm-order-2027.txt` in `icd10cm-code-descriptions-2027.zip` supplies all 98,403 concrete
   codes, order numbers, short descriptions, and long descriptions.

The XML contains 47,025 explicit diagnosis nodes but does not enumerate all seventh-character
extensions. The order file contains 98,403 concrete codes. For a concrete code absent from the XML,
the parent is its longest explicit XML diagnosis-code stem; e.g. `S52.521A` → `S52.521`. This is not
a general prefix hierarchy heuristic: explicit XML parentage always wins.

For sections, direct XML containment is the default. A provisional structural-range rule then nests a
section with no direct diagnosis beneath the narrowest empty sibling section whose official
`sectionIndex.first`/`last` bounds contain it; the section id is used only when the source index omits
that section. For example, `V00-X58` becomes the parent of `V00-V99` and `W00-X58`, and `V00-V99`
becomes the parent of `V00-V09` through `V98-V99`. The real FY27 build has 63 such `Section → Section`
links beneath 12 structural grouping sections. The XML index remains flat, so this is a documented
provisional model rather than an explicit source edge; see [`../../../TBD.md`](../../../TBD.md).

**Name policy for the FY27 update:** the preferred English name is rewritten from the current
staging English label to the official FY27 Tabular/order-file description. This is a same-locale
content refresh (`en` → `en`), not the ICD-10 translation-name workflow, and includes 2,137 changed
English labels in the FY25-to-FY27 comparison.

### What the order number means

The FY27 order file is a fixed-width, release-local list. Its first field is a five-digit, 1-based
record sequence: `00001` for `A00`, `00002` for `A00.0`, through `98403` for the final record. It is
**not** an ICD-10-CM identifier, an ordering priority, or clinical metadata; it only records the
position of that code in that particular FY27 file. An inserted, removed, or moved code shifts the
number of later rows, so annual changes to this field are expected and are not semantic changes.

### Properties and legacy enrichment

The staging FY25 source carries properties not all supplied by the FY27 CMS/NCHS package:

| Property | Origin / update rule |
|---|---|
| `Order number` | Official FY27 order-file sequence; preserve as an integer. |
| `Leaf Node` | Derived from the modeled hierarchy. |
| `excludes1`, `excludes2`, `useAdditionalCode`, `codeFirst`, `codeAlso`, `notes` | Official Tabular instructional notes, **regenerated from the FY27 Tabular XML for every chapter, section and diagnosis** (not carried from the legacy export). The extra key is the XML element name; the value is a list with one item per `<note>`, in document order, whitespace-collapsed. `Excludes1` ("not coded here") and `Excludes2` ("not included here") stay separate. A `<section>` that only wraps the same-code `<diag>` (e.g. `B10`, 38 cases) is one OCL concept, so its instructions are merged into that diagnosis. |
| `EXCLUDES1`, `EXCLUDES2`, `USE ADDITIONAL`, `CODE FIRST`, `CODE ALSO`, `Note` | Legacy upper-case labels of the same instructions. **Replaced** by the XML-named extras above on every updated concept; never carried. |
| `CUI`, `Semantic Types` | Legacy UMLS enrichment, absent from the CMS/NCHS FY27 package. Preserve unchanged until its provenance and intended use are reviewed. |

OCL update semantics matter: an update rebuilds the `names` collection from the line and replaces the
entire `extras` object whenever `extras` is supplied. The update artifact therefore cannot emit only
its newly computed fields; it needs a projection that preserves the target's non-governed extras alongside
the FY27-derived fields.

### Seventh-character instructions

Every `<diag>` with `sevenChrNote` + `sevenChrDef` (508 in FY27, always together) gets one description of
type `Seventh Character` (locale `en`), as a single line with `; ` separators (descriptions do not take
newlines): the note text, then `char - meaning` per extension. When exactly one concrete order-file code under
that diagnosis ends with the extension character, its code is appended. For `H40.10`:

```
One of the following 7th characters is to be assigned to code H40.10 to designate the stage of glaucoma; 0 - stage unspecified (H40.10X0); 1 - mild stage (H40.10X1); ...
```

A `<note>` the XML places inside `<sevenChrDef>` (8 in FY27: `S52`, `S72`, `S82`, `H34.81`, `H34.83`, `H35.31`,
`H35.32`, `W08`) is read as a note on the extension it follows and emitted as its own `; ` segment right after
it, e.g. `...; B - initial encounter for open fracture type I or II; initial encounter for open fracture NOS; C - ...`.
The codes come from the order file, never composed from the stem (the `X` placeholder in `H40.10X0` is there
because the order file has it). Stems with child diagnoses (430 of the 508) list the meanings without codes,
because the concrete codes depend on the child. `inclusionTerm` and `includes` are not part of this build yet;
the legacy synonyms that mirror `inclusionTerm` are preserved by an update (see `TBD.md`).

## OCL target and model

| Field | Value |
|---|---|
| Owner / Source | `US-NCHS` / `ICD-10-CM` |
| Root | `ICD-10-CM` — `ICD-10-CM TABULAR LIST of DISEASES and INJURIES` |
| Hierarchy | `grouped-by` |
| Classes / datatype | `Root` / `Chapter` / `Section` / `Diagnosis`; all use datatype `None` |
| Mappings | none |
| CUI / semantic types | legacy UMLS enrichments to preserve unchanged pending provenance review; not supplied by CMS/NCHS FY27 |

The topology mirrors read-only staging evidence: `A00-B99` hangs under the root, `A00-A09` under
`A00-B99`, `A00` under `A00-A09`, and `S52.521A` under `S52.521`.

## Inputs

| Asset | SHA-256 |
|---|---|
| `icd10cm-table-and-index-2027.zip` | `99b5c2be16ff53eab861cc0be4b1dacba27f687b8ff4bc700679944355037ee0` |
| `icd10cm-code-descriptions-2027.zip` | `93e3ad6004badf470c55bfe679b748ae88fd9b2b421851e409eec382c7713b9a` |

Both are published by CDC/NCHS at the FY27 directory. The raw ZIPs are Git-ignored; the pipeline
checks both hashes before it reads anything.

## Commands

```bash
uv run python terminologies/us-nchs/icd-10-cm/pipeline/cli.py verify-assets
uv run python terminologies/us-nchs/icd-10-cm/pipeline/cli.py build
```

The real FY27 build produced **98,685 lines**: 1 root, 22 chapters, 259 structural sections, and
98,403 concrete codes. It is a draft full-source refresh, not upload-ready, until it has been
compared with a fresh `US-NCHS/ICD-10-CM` staging snapshot and rehearsed locally.

## Output and upload

### Update against an environment's own export

```bash
# 1. the TARGET environment's own export (manual browser download is fine; keep its provenance sidecar)
# 2. one build per environment; local/staging bundles go to the git-ignored exports/<env>/build/icd10cm/
uv run python terminologies/us-nchs/icd-10-cm/pipeline/cli.py build \
  --export exports/staging/US-NCHS_ICD-10-CM_2025.zip --environment staging
```

`--export` and `--environment` go together. A line for a concept the target already holds keeps what the
release does not govern: the existing non-preferred names (English synonyms), descriptions other than the
seventh-character one, and any extra the release does not name. From the release come the English preferred name,
`Order number`, `Valid for submission`, `Leaf Node`, the instruction extras, the seventh-character description, the
parent link and the `concept_class` (`Root`/`Chapter`/`Section`/`Diagnosis`; UMLS extras are dropped and the legacy
upper-case instruction extras are replaced, counted in `legacy_instruction_extras_replaced`;
existing concepts whose class changes are counted in `concept_class_changed`). Ids in the release but not in the export are
created. Ids in the export but not in the release are **reported, never retired** (`not_in_release_ids` in
the audit) until the `TBD.md` retirement decision exists (the UMLS `T001`–`T204` ids are the exception, see below). No `external_id` is emitted.

Measured on the FY25 staging export (`ICD-10-CM 2025`, 98,030 concepts) against FY27: 97,829 updated,
856 created, 199 preferred names changed, 13,491 synonyms on 7,161 concepts preserved (a build without
`--export` would delete them), 61 parent links changed, and 201 ids not in the release (127 `T001`–`T204`,
41 synthetic ranges, 33 extension codes). The 41 ranges differ from the 38 counted in `TBD.md` and the 199
name changes from the 2,137 quoted above; both comparisons need reconciling before this README's earlier
figures are relied on.

The audit records `environment`, the export's path/SHA-256/concept count, and a per-environment
`upload_ready`; staging stays `false` until a local rehearsal passes.

### UMLS is out of every output (temporary policy)

Until a documented decision says otherwise, no environment receives UMLS content: every update drops `CUI` and
`Semantic Types` from `extras` (OCL replaces `extras` wholesale, so they disappear from each updated concept) and
appends one `__action: "DELETE"` line per active `T001`–`T204` concept. Those 127 identifiers are UMLS Semantic
Type codes, not ICD-10-CM codes: none of them is a code in the FY27 release (`not_in_release.semantic_type_ids` in
the audit lists them and none collides with a release id). The 41 synthetic ranges and 33 retired extension codes
are **not** retired; they are listed in the audit. `source.json` no longer declares `CUI` or `Semantic Types`.
`TBD.md` keeps the UMLS question open; reversing this means restoring the two properties and the preservation in
`project_update()`.

### Source configuration after a replica

A replica Source created from `source.create.json` has no declared properties, filters or display metadata: apply
`source.json` with `ocl_source_config.py --check --include-hierarchy`, send the printed PATCH by hand, and rebuild
the concept index; see [`../../../tests/README.md`](../../../tests/README.md).

### Draft full-source refresh (no export)

`bulkimport_icd10cm.bundle.zip` has exactly one NDJSON member. The `.parts.zip` file is a distribution
wrapper: extract it and manually upload its inner part ZIPs in numeric order, with **Update existing**
enabled. No pipeline code uploads to OCL. Without `--export` the bundle is a draft and must not be used to
update a populated Source.

## Tests

```bash
uv run python -m pytest tests/icd10cm
uv run python -m pytest
```
