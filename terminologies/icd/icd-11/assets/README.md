# ICD-11 assets (not committed)

Fetched inputs live here and are excluded from Git by `terminologies/.gitignore`
(`*/*/assets/**/*.zip`). Re-obtain them with:

```bash
uv run python terminologies/icd/icd-11/pipeline/cli.py fetch-assets
```

The download is verified against the pinned SHA-256 before it is kept, and a mismatch removes the
temporary file.

| Key | Authority | Edition (as declared) | Locale | Format | Retrieval URL | SHA-256 | Destination |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `simple-tabulation` | WHO | ICD-11 MMS 2026-01, header `Version:2026 Jan 17 - 05:30 UTC` | `en` | tab-separated text and XLSX in a ZIP, UTF-8 with BOM | <https://icdcdn.who.int/static/releasefiles/2026-01/SimpleTabulation-ICD-11-MMS-en.zip> | `f1356588f40953a83e3af2b662deab47c5e269f944d1ea4ed0cfeb2007c7cd39` | `who/2026-01/SimpleTabulation-ICD-11-MMS-en.zip` |

## Where this input comes from (edition discovery)

- The official 2026-01 release path returns the file whose hash is pinned above (4,214,980 bytes). It
  is byte-identical to the copy kept in the sibling `ciel-scripts` repository.
- The `releasefiles/2025-01/` path, used as the default URL in that repository's scripts, serves a
  different and older file (`Version:2025 Jan 24 - 22:30 UTC`, 3,852,427 bytes). Do not use it to
  reproduce this input.
- The archive holds `readme.txt` (column definitions), the tab-separated `.txt`, and the same table as
  `.xlsx`. The pipeline reads the `.txt`; its content was cross-checked against the XLSX (see the
  workspace README).
- License and redistribution terms were not verified from this repository.
