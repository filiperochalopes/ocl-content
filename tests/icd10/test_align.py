"""Alignment: exact-code acceptance, out-of-scope codes, unchanged labels, conflicts."""

from __future__ import annotations

from ocl_pipeline_loader import load
ACCEPTED = load("icd/icd-10", "align").ACCEPTED
DUPLICATE_CONFLICT = load("icd/icd-10", "align").DUPLICATE_CONFLICT
EXCLUDED_BY_CURATOR = load("icd/icd-10", "align").EXCLUDED_BY_CURATOR
NOT_IN_CANONICAL = load("icd/icd-10", "align").NOT_IN_CANONICAL
UNCHANGED = load("icd/icd-10", "align").UNCHANGED
align = load("icd/icd-10", "align").align
load_baseline = load("icd/icd-10", "canonical").load_baseline
AdapterResult = load("icd/icd-10", "model").AdapterResult
NameCandidate = load("icd/icd-10", "model").NameCandidate


def make(code: str, label: str, locale: str = "pt_BR", **kwargs) -> NameCandidate:
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


def result(*candidates: NameCandidate) -> AdapterResult:
    return AdapterResult(authority="TEST", locale=candidates[0].locale, edition="test edition", candidates=list(candidates))


def test_exact_code_match_with_different_label_is_accepted(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align([result(make("A09", "Diarreia e gastroenterite"))], index)
    assert alignment.counts() == {ACCEPTED: 1}
    assert alignment.by_code()["A09"][0].candidate.label == "Diarreia e gastroenterite"


def test_code_absent_from_canonical_is_out_of_scope(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align([result(make("U07.10", "COVID-19, forme respiratoire"))], index)
    assert alignment.counts() == {NOT_IN_CANONICAL: 1}
    assert alignment.by_code() == {}
    assert "code-absent-from-canonical-release" in alignment.decisions[0].reasons


def test_label_equal_to_canonical_english_name_is_unchanged(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align([result(make("A00", "  cholera  "))], index)
    assert alignment.counts() == {UNCHANGED: 1}


def test_two_labels_for_one_code_and_locale_conflict_as_a_group(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align(
        [result(make("A00", "Cólera", source_file="CID-10-CATEGORIAS.CSV"), make("A00", "Colera (alt)", source_file="other.csv"))],
        index,
    )
    assert alignment.counts() == {DUPLICATE_CONFLICT: 2}
    assert all("conflicting-labels" in ";".join(decision.reasons) for decision in alignment.decisions)


def test_same_code_in_different_locales_does_not_conflict(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align(
        [result(make("A00", "Cólera", locale="pt_BR"), make("A00", "Choléra", locale="fr"))],
        index,
    )
    assert alignment.counts() == {ACCEPTED: 2}
    assert sorted(decision.candidate.locale for decision in alignment.by_code()["A00"]) == ["fr", "pt_BR"]


def test_flags_are_carried_into_the_reasons(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align([result(make("A06.4", "Abcès amibien du foie", locale="fr", flags=("inline-markup",)))], index)
    assert "inline-markup" in alignment.decisions[0].reasons


def test_curated_exclusion_holds_a_reviewed_row_back(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align(
        [result(make("J09", "Influenza [gripe] devida a vírus identificado da gripe aviária"))],
        index,
        excluded={("J09", "pt_BR"): "national label names avian influenza; different meaning"},
    )
    assert alignment.counts() == {EXCLUDED_BY_CURATOR: 1}
    assert alignment.by_code() == {}
    assert alignment.decisions[0].reasons == (
        "curator-excluded:national label names avian influenza; different meaning",
    )


def test_exclusion_only_applies_to_the_named_locale(baseline_csv):
    index = load_baseline(baseline_csv)
    alignment = align(
        [result(make("A00", "Cólera", locale="pt_BR"), make("A00", "Choléra", locale="fr"))],
        index,
        excluded={("A00", "fr"): "pending review"},
    )
    assert alignment.counts() == {ACCEPTED: 1, EXCLUDED_BY_CURATOR: 1}
    assert sorted(decision.candidate.locale for decision in alignment.by_code()["A00"]) == ["pt_BR"]
