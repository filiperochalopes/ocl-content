# ICD-10-CM FY27 assets

Official CDC/NCHS FY27 files, effective October 1, 2026–September 30, 2027:

| File | Role | SHA-256 |
|---|---|---|
| `cdc/2027/icd10cm-table-and-index-2027.zip` | Tabular XML hierarchy | `99b5c2be16ff53eab861cc0be4b1dacba27f687b8ff4bc700679944355037ee0` |
| `cdc/2027/icd10cm-code-descriptions-2027.zip` | Full order file | `93e3ad6004badf470c55bfe679b748ae88fd9b2b421851e409eec382c7713b9a` |

Source directory: `https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2027/`.

FY27 moved the order file from the table-and-index package to the code-descriptions package. The
pipeline deliberately needs both files; do not substitute the FY27 addenda files, which describe the
delta rather than the complete release.
