# WHO-ATC assets (fetched on demand; not committed)

Fetched data files live under this directory but are excluded from Git (`terminologies/.gitignore`).
This file documents what they are and how to reproduce them.

## `bioportal/submission-<N>/ATC.ttl`

The NCBO BioPortal UMLS2RDF export of the ATC ontology, for one specific, numbered, **immutable**
BioPortal submission.

| Field | Value |
|---|---|
| Submission | 25 |
| `owl:versionInfo` (inside the file) | `2025_02_10` |
| `dcterms:source` (inside the file) | `UMLS 2025AB` |
| Retrieval URL | `https://data.bioontology.org/ontologies/ATC/submissions/25/download?apikey=<your key>` |
| SHA-256 | `af99bc159c72f0ef70c18065d68f61022bf6074efe65585eb5e826527dbcec4a` |
| Local path | `bioportal/submission-25/ATC.ttl` |
| Bytes | 3,817,393 |
| License / redistribution | BioPortal re-publishes UMLS-derived content under UMLS terms; not independently verified here |

A BioPortal submission download needs a personal API key (free: create an account at
<https://bioportal.bioontology.org/account>), passed as `?apikey=...` in the query string. The key is
never committed, logged, or printed by this pipeline; it is read once from `$BIOPORTAL_API_KEY` by
`pipeline/assets.py::fetch_ttl`. If you already downloaded a copy by hand (as a curator did on
2026-10-12, from the ATC ontology page at <https://bioportal.bioontology.org/ontologies/ATC>), place
it at the path above and `fetch-assets` will verify its hash instead of downloading again.

A new BioPortal submission is a **new, higher submission number**; when one ships, add its own entry
to `PINNED_SUBMISSIONS` in `pipeline/assets.py` (never overwrite submission 25's recorded hash) and
update `LATEST_SUBMISSION`.

## `atcddd/atc_alterations_cumulative.html`

The WHO Collaborating Centre's cumulative list of ATC code alterations (replacements), retained only
for optional structural/historical review. It is **not** used to determine retirement, enrich concept
names, or create `REPLACED BY` mappings: the lifecycle rule is the exact difference between an
immutable OCL snapshot and the current upstream ontology.

| Field | Value |
|---|---|
| Retrieval URL | `https://atcddd.fhi.no/atc_ddd_alterations__cumulative/atc_alterations/` |
| Format | one HTML `<table>`; live column order (2026-10-12): Previous ATC code, Substance name, New ATC code, Year changed |
| License / redistribution | WHO Collaborating Centre for Drug Statistics Methodology; not independently verified here |
| Hash pinning | **not pinned** — this is a living cumulative list WHO/FHI append to every year, not a dated release. Each build records the SHA-256 of whichever copy was actually used, in `bulkimport_audit.json`, for provenance only |

No API key is needed for this page.

## Where these inputs come from — edition discovery

- BioPortal's ATC ontology page (<https://bioportal.bioontology.org/ontologies/ATC>) lists every
  submission; the "Submissions" tab shows each one's date and a download link with the submission
  number in the URL.
- The official, continuously updated classification is published at
  <https://atcddd.fhi.no/atc_ddd_index/> and <https://www.who.int/tools/atc-ddd-toolkit>; BioPortal's
  periodic UMLS-derived export can lag it (see `../README.md`, "Known limits").
