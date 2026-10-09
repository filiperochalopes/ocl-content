# ICD-10 asset inputs

Canonical releases and national editions consumed by `../pipeline/`. Data files are fetched on
demand and are **not** committed; only this README is tracked. Verify every file against its
pinned SHA-256 before use.

```bash
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset all
python3 terminologies/icd/icd-10/pipeline/cli.py fetch-assets --asset datasus-csv --force
```

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
