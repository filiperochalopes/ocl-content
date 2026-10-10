# ICD-10 asset inputs

Canonical releases and national editions consumed by `../pipeline/`. Data files are fetched on
demand and are **not** committed; only this README is tracked. Verify every file against its
pinned SHA-256 before use.

```bash
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset all
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset datasus-csv --force
```

## Where these inputs come from (edition discovery)

The WHO publishes the ICD-10 ClaML/Meta releases behind an index page:

| Page | What it is |
| --- | --- |
| <https://icdcdn.who.int/icd10/index.html> | The release index: every downloadable ICD-10 edition, in ClaML and Meta formats |
| <https://icdcdn.who.int/icd10/clamlinfo.html> | Description of the ClaML format ("more info" next to each ClaML link) |
| <https://icdcdn.who.int/icd10/metainfo.html> | Description of the Meta format ("more info" next to each Meta link) |

Verified on **2026-10-09** (links on that page are relative to it). The editions it lists:

| Edition (as labelled on the index) | ClaML | Meta |
| --- | --- | --- |
| **ICD-10 2019 version (including COVID-19 updates)** | `claml/icd102019en.xml.zip` | `meta/icd102019enMeta.zip` |
| ICD-10 2016 version | `claml/icd102016en.xml.zip` | `meta/icd102016enMeta.zip` |
| ICD-10 2015 version | `claml/icd102015en.xml.zip` | — |
| ICD-10 2014 version | `claml/icd102014en.xml.zip` | — |
| ICD-10 2010 version | `claml/icd102010en.xml.zip` | `meta/icd102010enMeta.zip` |
| ICD-10 2nd Edition / 2008 | `claml/icd102008en.xml.zip` | `meta/icd102008enMeta.zip` |

**Why the 2019 release is the one pinned here**: it is the newest edition the index offers (the ICD-10
line itself is frozen — work continues in ICD-11), and it is the one that carries the COVID-19
updates (`U07.1`, `U07.2`) the WHO/ICD-10-WHO Source already contains. Its ClaML file declares
`2019-covid-expanded` in its own `Title`, which is recorded verbatim in the table below.

The **Meta** sibling (`meta/icd102019enMeta.zip`, 237,071 bytes, HTTP 200) carries mortality/tabulation
metadata as separate files. It has no consumer in this pipeline — the `MortB*`/`MortL*` elements the
extraction sees are the ones embedded in the ClaML file — so it is not registered as an asset. If a
future step needs the tabulation lists, add it here with its hash first.

Re-check this page when a new canonical baseline is considered: an edition that is not listed above
cannot be pinned as a SHA-256 without first deciding that the Source changes release.

## Pinned sources

| Asset | Authority | Edition (as declared) | Locale | Format | Retrieval URL | SHA-256 | Destination |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `datasus-csv` | DATASUS / Ministério da Saúde (Brasil) | CID-10 V2008 download page; the XML declares `V2007` | `pt_BR` | semicolon CSV, ISO-8859-1 | http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip | `84f23809275575f751255048064bbb244b0de33fd5987ab98df0f98e5f5d2c95` | `datasus/2008/CID10CSV.zip` |
| `datasus-xml` | DATASUS | CID-10 V2008 page; root attribute `versao="V2007"` | `pt_BR` | DATASUS-specific XML, ISO-8859-1, DTD entities `cruz`/`aster` | http://www2.datasus.gov.br/cid10/V2008/downloads/CID10XML.zip | `1f2f34076e50a28510aac7d2068003337aa05df1f4969571b46fd0dfa6de1385` | `datasus/2008/CID10XML.zip` |
| `who-claml` | WHO | title declares `2019-covid-expanded`, date `2020-03-22`; Identifier `icd10_20210322` | `en` | ClaML | https://icdcdn.who.int/icd10/claml/icd102019en.xml.zip | `344c571aa9aed3b9ad1c80261b7828c45cfb5fc0b1a5da64aecef354dff5b3d9` | `who/icd102019en/icd102019en.xml.zip` |
| `atih-claml` | ATIH (France) | CIM-10-FR 2024, `2024-01-01` | `fr` | ClaML with `FM`/`OMS` label variants | https://www.atih.sante.fr/sites/default/files/content/documents/cim10fr2024syst_claml_20231215.zip | `6f7b631d2da9f932b85ed7397c7476169c869ba3992c8f862d2c918332a15c55` | `atih/2024/cim10fr2024syst_claml_20231215.zip` |

Notes recorded from the fetch:

- The ATIH ZIP redirects to
  `https://www.atih.sante.fr/sites/default/files/content/documents/cim10fr2024syst_claml_20231215.zip`,
  which is the URL pinned above. Its XML is **byte-identical** to the tracked legacy copy in
  [`../../../ICD-10 for OCL/cim10fr2024syst_claml_20231215/`](../../../ICD-10%20for%20OCL/cim10fr2024syst_claml_20231215/),
  which is why the French pipeline input defaults to that tracked path and does not need a copy here.
- DATASUS serves the files over plain HTTP only; the HTTPS origin refused the connection during
  the study. The pinned SHA-256 is the integrity control for that HTTP retrieval.
- `datasus-xml` is documented for completeness. The current pipeline reads the DATASUS CSV
  tables; no consumer exists yet for the DATASUS XML.

## License and redistribution (not verified)

Redistribution terms were not established for these files during the study. Do not commit a
fetched data file or redistribute it from this repository until the license is confirmed; the
fetch helper exists so each operator obtains their own copy and verifies the hash.

## What these files are not

The French file is the **CIM-10 français** and the DATASUS file is the **CID-10 brasileiro**:
national editions of ICD-10, not translations of the English release. Their codes, chapter
numbering, and content differ from the WHO English release, so code-level alignment is a
candidate for a name review, not proof that the two entries mean the same thing.
