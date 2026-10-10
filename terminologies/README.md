# Terminology workspace README template

Every terminology workspace under `terminologies/<authority>/<terminology>/` keeps one
`README.md` and one reviewed `source.json` (`CONTRIBUTING.md`). Copy the sections below and
fill them with evidence from the assets actually present. Do not keep a section you cannot
support with a file, a URL, or a command.

## Required sections

1. **Scope and compatibility** — what this workspace covers, what it deliberately does not do,
   and which legacy locations remain authoritative for assets that were not migrated yet.
2. **OCL target** — owner, Source, synthetic root concept ID, hierarchy meaning.
3. **Source configuration** — what `source.json` declares and how to validate it locally.
4. **Validate and synchronize** — local check and read-only check that prints the proposed patch; applying it is manual.
5. **Validation expectations** — the pre-write checks and the post-write read-back.
6. **Data sources and provenance** — every input file this workspace consumes.
7. **Pipeline and output** — the scripts, their commands, and the artifacts they write.
8. **Related assets** — repository-relative links to inputs and shared tooling.

## Data sources and provenance

The provenance table is mandatory whenever a workspace consumes more than its own terminology
release, including canonical releases, national editions, and translations. List one row per
file; a translation is an edition of a national classification, not a generic "language file".

| Field | Meaning |
| --- | --- |
| Authority | Publisher or agency that issues the file (for example WHO, ATIH, DATASUS) |
| Edition / release | The edition as declared by the file or page, verbatim, including contradictory values |
| Locale | The language/country of the labels the file contributes (`en`, `pt_BR`, `fr`) |
| Format | `ClaML`, `CSV`, `XML`, `NDJSON`, … |
| Retrieval URL | The exact URL the copy came from, including the final redirect target when it differs |
| SHA-256 | Hash of the fetched bytes, so the same file can be re-verified |
| Local path | Repository path or fetch destination; fetched data files are excluded from Git |
| License / redistribution | What is known, and explicitly what is not verified |
| Alignment rule | How its codes are matched to the canonical release (see below) |

## Alignment rules to document

State, per source, whether a code match is trusted, and why:

- A code-level match aligns **names only**; it never creates concepts, changes hierarchy, or
  asserts equivalence.
- Codes present only in a national edition are **out of scope** and must not be promoted.
- An exact code match across editions is not proof of an identical clinical meaning. Record
  where a human decision is required and where one was taken.
- Normalizations that change a token (separators, chapter numbering, punctuation) are recorded
  with the original value and the applied rule; the pipeline must never "fix" a token it cannot
  validate to force a match.

## Output

Bulk-import artifacts live in the workspace's `output/` directory:

```text
<terminology>/output/
├── bulkimport_part_001.ndjson      # ordered, size-capped      → NOT versioned
├── bulkimport_bundle.ndjson        # every line, in order      → NOT versioned
├── alignment_report.csv            # review surface            → NOT versioned
├── bulkimport_audit.json           # provenance, counts, hashes → versioned
└── bulkimport_<name>.zip           # parts + bundle + manifest  → versioned
```

- Cut parts on resource boundaries **in order**, cap each one (2 MB is the house default), and
  verify that concatenating them reproduces the bundle. Never split a single resource.
- Also emit the pretty-printed before/after **dev audit pair** in the same run (same IDs, same
  order, same fields) so a curator can review the proposal as a diff in a JSON-aware viewer
  (diffchecker.com); keep it opt-in, label it a review aid, and never version it.
- Ship the parts, the whole bundle, and a manifest (target, mode, upload-ready flag, per-part
  SHA-256) inside one zip; that zip plus the audit are the only versioned artifacts. Parts and
  reports are byte-reproducible from the inputs the audit records, so they do not belong in Git
  history.
- Let the operator choose the compression method: `deflate` (level 9, portable) by default, with a
  higher-ratio option such as `lzma` documented alongside its compatibility caveat.
- State whether the committed artifacts are upload-ready or a draft that must be regenerated from
  a live or exported snapshot before upload, and name the command that does it.

## Uploading stays manual

Do not build — and do not document — a pipeline, helper, or skill that uploads a bulk import to
OCL through the API. Generation ends with local artifacts; an operator uploads the extracted parts
through the OCL bulk-import form, in numeric order, reusing one Queue ID. Record that in the audit
and in the archive manifest so the hand-off cannot be mistaken for an automated step.
