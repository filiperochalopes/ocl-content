"""GPS release parsing and projection tests."""

from __future__ import annotations

import zipfile

import pytest

from ocl_pipeline_loader import load

reader = load("snomed/gps", "gps_release")
build = load("snomed/gps", "build_bulkimport").build


def test_reads_release_and_counts(gps_zip):
    release = reader.read(gps_zip)
    assert release.release_date == "2026-01-01"
    assert len(release.concepts) == 2
    assert release.active_count == 1 and release.inactive_count == 1


def test_projects_exact_flat_gps_semantics(gps_zip):
    result = build(reader.read(gps_zip))
    active, inactive = result.lines
    assert active["id"] == "22298006" and active["retired"] is False
    assert inactive["id"] == "80146002" and inactive["retired"] is True
    assert active["concept_class"] == "disorder" and active["datatype"] == "None"
    assert active["names"] == [
        {"name": "Myocardial infarction (disorder)", "locale": "en", "locale_preferred": False, "name_type": "Fully-Specified"},
        {"name": "Myocardial infarction", "locale": "en", "locale_preferred": True},
    ]
    assert "parent_concept_urls" not in active and "mappings" not in active and "extras" not in active


def test_projects_fsn_semantic_tag_as_concept_class_and_untyped_preferred_name(gps_zip):
    result = build(reader.read(gps_zip))
    active = result.lines[0]
    assert active["concept_class"] == "disorder"
    assert active["names"][0]["name_type"] == "Fully-Specified"
    assert active["names"][1] == {"name": "Myocardial infarction", "locale": "en", "locale_preferred": True}


@pytest.mark.parametrize("fsn", ["Myocardial infarction disorder", "Myocardial infarction ( )"])
def test_fsn_without_one_nonempty_trailing_semantic_tag_is_refused(gps_zip, fsn):
    release = reader.read(gps_zip)
    malformed = release.concepts[0].__class__("22298006", True, fsn, "Myocardial infarction", 2)
    release.concepts[0] = malformed
    with pytest.raises(ValueError, match="trailing semantic tag"):
        build(release)


def test_duplicate_ids_are_refused(gps_zip, tmp_path):
    duplicate = tmp_path / "SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.txt", "ConceptID\tActive\tFSN\tUSPreferredTerm\n1\t1\tA (x)\tA\n1\t0\tB (x)\tB\n")
        archive.writestr("Readme.txt", "Creative Commons Attribution-NoDerivatives 4.0 International Public License")
    with pytest.raises(ValueError, match="duplicate"):
        build(reader.read(duplicate))


def test_bad_active_value_is_refused(gps_zip, tmp_path):
    bad = tmp_path / "SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.txt", "ConceptID\tActive\tFSN\tUSPreferredTerm\n1\tX\tA (x)\tA\n")
        archive.writestr("Readme.txt", "Creative Commons Attribution-NoDerivatives 4.0 International Public License")
    with pytest.raises(ValueError, match="Active"):
        reader.read(bad)


def test_missing_licence_marker_is_refused(tmp_path):
    bad = tmp_path / "SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("SnomedINTL_GPSRelease_PRODUCTION_20260101T120000Z.txt", "ConceptID\tActive\tFSN\tUSPreferredTerm\n1\t1\tA (x)\tA\n")
        archive.writestr("Readme.txt", "missing licence")
    with pytest.raises(ValueError, match="CC BY-ND"):
        reader.read(bad)
