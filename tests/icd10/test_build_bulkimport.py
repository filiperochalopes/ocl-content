"""Bulk-import build: projection, locale handling, part writing, idempotency, determinism."""

from __future__ import annotations

import json

import pytest

from pipeline.align import align
from pipeline.build_bulkimport import (
    ConceptState,
    build,
    write_alignment_csv,
    write_audit_pair,
    write_bundle,
    write_parts,
)
from pipeline.canonical import load_baseline
from pipeline.model import AdapterResult, NameCandidate

PROJECTION_KEYS = {"type", "id", "concept_class", "names", "descriptions", "extras", "owner", "owner_type", "source"}


def candidate(code: str, label: str, locale: str, **kwargs) -> NameCandidate:
    return NameCandidate(
        code=code,
        locale=locale,
        label=label,
        authority=kwargs.pop("authority", "TEST"),
        edition=kwargs.pop("edition", "test edition"),
        kind=kwargs.pop("kind", "category"),
        source_file=kwargs.pop("source_file", "test.csv"),
        source_code=kwargs.pop("source_code", code),
        source_row=kwargs.pop("source_row", 2),
        **kwargs,
    )


def prepare(baseline_csv, *candidates: NameCandidate):
    index = load_baseline(baseline_csv)
    results = [
        AdapterResult(authority="TEST", locale=locale, edition="test edition", candidates=list(group))
        for locale, group in _group_by_locale(candidates)
    ]
    alignment = align(results, index)
    states = {code: ConceptState.from_canonical(index.concepts[code]) for code in alignment.by_code()}
    return index, alignment, states


def _group_by_locale(candidates):
    grouped: dict[str, list[NameCandidate]] = {}
    for item in candidates:
        grouped.setdefault(item.locale, []).append(item)
    return grouped.items()


def test_line_carries_the_complete_projection(baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("A00.0", "Cólera devida a Vibrio cholerae 01, biótipo cholerae", "pt_BR"),
        candidate("A00.0", "À Vibrio cholerae 01, biovar cholerae", "fr"),
    )
    result = build(alignment, states)
    assert len(result.lines) == 1
    line = result.lines[0]
    assert set(line) == PROJECTION_KEYS
    assert line["owner"] == "WHO" and line["source"] == "ICD-10-WHO" and line["owner_type"] == "Organization"
    assert line["id"] == "A00.0" and line["concept_class"] == "Code"
    locales = {name["locale"]: name for name in line["names"]}
    assert set(locales) == {"en", "pt_BR", "fr"}
    assert locales["en"]["name"] == "Cholera due to Vibrio cholerae 01, biovar cholerae"
    assert locales["en"]["locale_preferred"] is True
    assert locales["pt_BR"]["locale_preferred"] is True
    assert line["extras"] == {"hierarchy_level": "4", "chapter_number": "1"}


def test_only_names_change_not_structure(baseline_csv):
    index, alignment, states = prepare(baseline_csv, candidate("A00", "Cólera", "pt_BR"))
    result = build(alignment, states)
    before, after = result.before[0], result.after[0]
    assert before["id"] == after["id"]
    assert before["concept_class"] == after["concept_class"]
    assert before["descriptions"] == after["descriptions"]
    assert before["extras"] == after["extras"]
    assert before["names"] == after["names"][:-1]


def test_build_is_idempotent_over_its_own_after_state(baseline_csv):
    index, alignment, states = prepare(baseline_csv, candidate("A00", "Cólera", "pt_BR"), candidate("A00", "Choléra", "fr"))
    first = build(alignment, states)
    after_states = {line["id"]: ConceptState.from_export(line) for line in first.after}
    second = build(alignment, after_states)
    assert second.lines == []
    assert second.status_counts() == {"NO_CHANGE": 1}
    assert all(outcome.unchanged for outcome in second.outcomes)


def test_existing_locale_name_is_never_replaced(baseline_csv):
    index, alignment, states = prepare(baseline_csv, candidate("A00", "Cólera (nova)", "pt_BR"))
    state = ConceptState.from_export(
        {
            "id": "A00",
            "concept_class": "Code",
            "names": [
                {"name": "Cholera", "locale": "en", "locale_preferred": True},
                {"name": "Cólera (existente)", "locale": "pt_BR", "locale_preferred": True},
            ],
            "extras": {"hierarchy_level": "3"},
        }
    )
    result = build(alignment, {"A00": state})
    assert result.lines == []
    assert result.outcomes[0].conflicts
    assert "Cólera (existente)" not in json.dumps(result.lines)


def test_repeated_label_in_the_same_locale_is_already_present(baseline_csv):
    index, alignment, states = prepare(baseline_csv, candidate("A00", "Cólera", "pt_BR"))
    first = build(alignment, states)
    state = ConceptState.from_export(first.after[0])
    second = build(alignment, {"A00": state})
    assert second.lines == []
    assert second.outcomes[0].unchanged


def test_parts_are_limited_by_size_and_preserve_order(tmp_path, baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("A00", "Cólera", "pt_BR"),
        candidate("A09", "Diarreia e gastroenterite", "pt_BR"),
        candidate("J09", "Influenza aviária", "pt_BR"),
    )
    result = build(alignment, states)
    limit = 600
    parts = write_parts(tmp_path, result.lines, max_bytes=limit)
    assert len(parts) > 1
    assert all(part.bytes <= limit for part in parts)
    assert [part.name for part in parts] == [f"bulkimport_part_{n:03d}.ndjson" for n in range(1, len(parts) + 1)]
    combined = b"".join((tmp_path / part.name).read_bytes() for part in parts)
    bundle = write_bundle(tmp_path, result.lines)
    assert combined == (tmp_path / bundle.name).read_bytes()
    assert bundle.lines == len(result.lines)
    for part in parts:
        for line in (tmp_path / part.name).read_text(encoding="utf-8").strip().split("\n"):
            assert set(json.loads(line)) == PROJECTION_KEYS


def test_a_resource_larger_than_the_limit_is_refused(tmp_path, baseline_csv):
    index, alignment, states = prepare(baseline_csv, candidate("A00", "Cólera", "pt_BR"))
    result = build(alignment, states)
    with pytest.raises(ValueError, match="cannot be split across parts"):
        write_parts(tmp_path, result.lines, max_bytes=50)


def test_a_smaller_rerun_removes_stale_parts(tmp_path, baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("A00", "Cólera", "pt_BR"),
        candidate("A09", "Diarreia e gastroenterite", "pt_BR"),
        candidate("J09", "Influenza aviária", "pt_BR"),
    )
    result = build(alignment, states)
    assert len(write_parts(tmp_path, result.lines, max_bytes=500)) > 1
    assert len(write_parts(tmp_path, result.lines, max_bytes=10 ** 6)) == 1
    assert [path.name for path in sorted(tmp_path.glob("bulkimport_part_*.ndjson"))] == ["bulkimport_part_001.ndjson"]


def test_build_is_deterministic(baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("A00.0", "Cólera devida a Vibrio cholerae 01, biótipo cholerae", "pt_BR"),
        candidate("A00.0", "À Vibrio cholerae 01, biovar cholerae", "fr"),
    )
    first = json.dumps(build(alignment, states).lines, ensure_ascii=False)
    second = json.dumps(build(alignment, states).lines, ensure_ascii=False)
    assert first == second


def test_alignment_report_lists_every_decision(tmp_path, baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("U07.10", "COVID-19, forme respiratoire", "fr"),
        candidate("A00", "Cólera", "pt_BR"),
    )
    path = tmp_path / "alignment_report.csv"
    write_alignment_csv(path, alignment)
    rows = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(rows) == 3  # header + both decisions
    assert "not-in-canonical" in path.read_text(encoding="utf-8")


def test_audit_pair_is_a_pretty_printed_diffable_pair(tmp_path, baseline_csv):
    index, alignment, states = prepare(
        baseline_csv,
        candidate("A00", "Cólera", "pt_BR"),
        candidate("A09", "Diarreia e gastroenterite", "pt_BR"),
    )
    result = build(alignment, states)
    info = write_audit_pair(tmp_path, result.before, result.after)
    assert info.before == "bulkimport_before.dev.audit.json"
    assert info.after == "bulkimport_after.dev.audit.json"
    assert info.concepts == len(result.lines)

    before = json.loads((tmp_path / info.before).read_text(encoding="utf-8"))
    after = json.loads((tmp_path / info.after).read_text(encoding="utf-8"))
    # Same IDs, same order, same fields: a diff shows only the changed values.
    assert [entry["id"] for entry in before] == [entry["id"] for entry in after]
    assert [sorted(entry) for entry in before] == [sorted(entry) for entry in after]
    assert all(entry["names"] != other["names"] for entry, other in zip(before, after))
    # Pretty-printed, not one line per concept.
    assert len((tmp_path / info.before).read_text(encoding="utf-8").split("\n")) > len(before)


def test_audit_pair_refuses_mismatched_id_sets(tmp_path):
    with pytest.raises(ValueError, match="same concept IDs in the same order"):
        write_audit_pair(tmp_path, [{"id": "A00"}], [{"id": "A01"}])
