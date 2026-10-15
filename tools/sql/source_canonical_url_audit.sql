-- Read-only audit of Source canonical_url in the LOCAL oclapi2 database.
--
-- Scope: local Docker oclapi2 only (container oclapi2-db-1, database "postgres").
-- Staging and production have no direct DB access; check them with a read-only
-- REST GET of /orgs/<owner>/sources/<source>/ (see the guide below) and compare
-- the same expected values.
--
-- Expected values come from each terminologies/<...>/source.json "canonical_url".
-- When a source.json changes, update the VALUES list here in the same commit.
--
-- Run (SELECT only, no writes):
--   docker exec -i oclapi2-db-1 psql -U postgres -d postgres -f - \
--     < tools/sql/source_canonical_url_audit.sql
--
-- Verdicts:
--   OK        actual canonical_url equals the source.json value
--   MISMATCH  canonical_url differs, including NULL/empty where source.json sets one
--   MISSING   the Source (or its organization) was not found in this database

WITH expected (org_mnemonic, source_mnemonic, expected_canonical_url, source_json) AS (
  VALUES
    ('SNOMED-International', 'SNOMED-GPS',  'http://snomed.info/sct?fhir_vs=refset/787778008', 'terminologies/snomed/gps/source.json'),
    ('WHO',                  'WHOATC',       'http://www.whocc.no/atc',                             'terminologies/who/atc/source.json'),
    ('WHO',                  'ICD-10-WHO',   'http://hl7.org/fhir/sid/icd-10',                      'terminologies/who/icd-10/source.json'),
    ('WHO',                  'ICD-11-WHO',   'http://id.who.int/icd/release/11/mms',                'terminologies/who/icd-11/source.json'),
    ('US-NCHS',              'ICD-10-CM',    'http://hl7.org/fhir/sid/icd-10-cm',                   'terminologies/us-nchs/icd-10-cm/source.json')
)
SELECT
    e.org_mnemonic,
    e.source_mnemonic,
    s.version,
    s.is_latest_version                                       AS latest,
    s.canonical_url                                           AS actual_canonical_url,
    e.expected_canonical_url                                  AS expected_canonical_url,
    CASE
        WHEN s.id IS NULL THEN 'MISSING'
        WHEN s.canonical_url IS NOT DISTINCT FROM e.expected_canonical_url THEN 'OK'
        ELSE 'MISMATCH'
    END                                                       AS verdict,
    e.source_json
FROM expected e
LEFT JOIN organizations o ON o.mnemonic = e.org_mnemonic
LEFT JOIN sources s       ON s.organization_id = o.id AND s.mnemonic = e.source_mnemonic
ORDER BY e.source_mnemonic, s.version;
