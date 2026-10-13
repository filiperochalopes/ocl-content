"""Extract the canonical ICD-10 structure directly from the WHO ClaML release.

This is the extractor the alignment baseline is verified against. It reproduces the reviewed
2021 CSV baseline from the WHO file:

* ``Class`` elements become Chapter / Group / Code concepts (WHO ``block`` becomes ``Group``);
* a chapter's roman numeral becomes the integer chapter number the baseline uses;
* ``ModifiedBy``/``ModifierClass`` are expanded into the derived codes (``E10`` + ``.0`` →
  ``E10.0``) whose preferred name is ``"<parent preferred>: <modifier label>"`` — the rule that
  reproduces every derived code present in the baseline, name for name;
* a modifier subcode written without a separator on a three-character parent gets the dot
  (``I70`` + ``0`` → ``I70.0``) and is flagged, because the source does not write it.

Extras are deliberately left empty: the baseline's ``hierarchy_level``, ``chapter_number``,
``Classification_Place`` and ``Terminal_Node`` come from the legacy import, not from this file,
and the WHO ``Meta`` elements (mortality codes) are a different set. Never upload an artifact
whose extras came from here — use the CSV baseline or hydrate from HEAD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..canonical import CanonicalConcept
from ..xmlsafe import parse_claml, preferred_label_text

CLASS_KINDS = {"chapter": "Chapter", "block": "Group", "category": "Code"}


def _xml_path(source: Path) -> Path:
    """Accept the WHO ClaML zip or an already-extracted .xml file."""
    source = Path(source)
    if source.suffix.lower() != ".zip":
        return source
    import zipfile

    with zipfile.ZipFile(source) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".xml") and not Path(name).name.startswith(".")
        ]
        if not members:
            raise ValueError(f"{source}: no XML member inside the archive")
        payload = archive.read(members[0])
        target = source.with_name(f"{source.stem}.extracted.xml")
        if not target.is_file() or target.read_bytes() != payload:
            target.write_bytes(payload)
    return target


ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18,
    "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22,
}


@dataclass
class Extraction:
    concepts: list[CanonicalConcept] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)

    @property
    def by_id(self) -> dict[str, CanonicalConcept]:
        return {concept.id: concept for concept in self.concepts}


def compose_derived_code(parent: str, subcode: str) -> tuple[str, bool]:
    """Return ``(code, dot_inserted)`` for a modifier subcode appended to a parent code."""
    if subcode.startswith("."):
        return parent + subcode, False
    if len(parent) == 3:
        return f"{parent}.{subcode}", True
    return parent + subcode, False


def extract(source: Path) -> Extraction:
    root = parse_claml(_xml_path(source))
    extraction = Extraction()
    extraction.stats["edition"] = _title(root)
    extraction.stats["declared_lang"] = next(
        (meta.get("value") for meta in root.findall("Meta") if meta.get("name") == "lang"), None
    )
    names: dict[str, str] = {}
    seen: set[str] = set()

    for element in root.findall("Class"):
        kind = element.get("kind") or ""
        source_code = (element.get("code") or "").strip()
        concept_class = CLASS_KINDS.get(kind)
        if concept_class is None:
            extraction.skipped.append({"reason": "unsupported-class-kind", "source_code": source_code, "kind": kind})
            continue
        name = preferred_label_text(element)
        if not name:
            extraction.skipped.append({"reason": "no-preferred-label", "source_code": source_code})
            continue
        if kind == "chapter":
            number = ROMAN.get(source_code.upper())
            if number is None:
                extraction.skipped.append({"reason": "unrecognized-chapter-numeral", "source_code": source_code})
                continue
            concept_id = str(number)
            if concept_id != source_code:
                extraction.stats["roman_chapters"] = extraction.stats.get("roman_chapters", 0) + 1
        else:
            concept_id = source_code
        if concept_id in seen:
            extraction.skipped.append({"reason": "duplicate-concept-id", "source_code": source_code})
            continue
        seen.add(concept_id)
        names[concept_id] = name
        extraction.concepts.append(
            CanonicalConcept(
                id=concept_id,
                concept_class=concept_class,
                name=name,
                description="",
                extras={},
                parent_concept_urls="",
            )
        )

    modifier_labels: dict[str, list[tuple[str, str]]] = {}
    for element in root.findall("ModifierClass"):
        rubric_label = preferred_label_text(element)
        code = (element.get("code") or "").strip()
        modifier = (element.get("modifier") or "").strip()
        if not code or not modifier:
            continue
        modifier_labels.setdefault(modifier, []).append((code, rubric_label))

    derived = 0
    dotted = 0
    for element in root.findall("Class"):
        parent = (element.get("code") or "").strip()
        if parent not in names:
            continue
        for modified_by in element.findall("ModifiedBy"):
            modifier = (modified_by.get("code") or "").strip()
            entries = modifier_labels.get(modifier)
            if not entries:
                extraction.skipped.append(
                    {"reason": "modified-by-without-modifierclass", "source_code": parent, "modifier": modifier}
                )
                continue
            for subcode, label in entries:
                if not label:
                    extraction.skipped.append(
                        {"reason": "modifier-label-missing", "source_code": parent, "modifier": modifier, "subcode": subcode}
                    )
                    continue
                concept_id, inserted = compose_derived_code(parent, subcode)
                if inserted:
                    dotted += 1
                if concept_id in seen:
                    extraction.skipped.append({"reason": "derived-code-collision", "source_code": concept_id})
                    continue
                seen.add(concept_id)
                extraction.concepts.append(
                    CanonicalConcept(
                        id=concept_id,
                        concept_class="Code",
                        name=f"{names[parent]}: {label}",
                        description="",
                        extras={},
                        parent_concept_urls="",
                    )
                )
                derived += 1

    extraction.stats["classes"] = sum(1 for element in root.findall("Class"))
    extraction.stats["modifier_derived"] = derived
    extraction.stats["modifier_derived_dot_inserted"] = dotted
    extraction.stats["modifier_classes"] = sum(1 for _ in root.findall("ModifierClass"))
    extraction.stats["concepts"] = len(extraction.concepts)
    extraction.stats["class_counts"] = _class_counts(extraction.concepts)
    return extraction


def _title(root) -> dict[str, str | None]:
    title = root.find("Title")
    if title is None:
        return {}
    return {"name": title.get("name"), "version": title.get("version"), "date": title.get("date")}


def _class_counts(concepts: list[CanonicalConcept]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for concept in concepts:
        counts[concept.concept_class] = counts.get(concept.concept_class, 0) + 1
    return dict(sorted(counts.items()))


def verify(extraction: Extraction, baseline: dict[str, CanonicalConcept]) -> dict:
    """Compare the extraction with a baseline: IDs, names, and what each side has alone.

    Name mismatches are classified: the legacy baseline composes some names as
    ``"<parent context>: <label>"`` (for example ``Malignant neoplasm: External upper lip``),
    while the WHO file carries the bare label. A mismatch that is only that prefix is counted
    separately from a genuinely different label.
    """
    extracted = extraction.by_id
    both = sorted(set(extracted) & set(baseline))
    mismatches = [
        {"id": concept_id, "who": extracted[concept_id].name, "baseline": baseline[concept_id].name}
        for concept_id in both
        if extracted[concept_id].name != baseline[concept_id].name
    ]
    prefixed = [
        entry for entry in mismatches if entry["baseline"].endswith(f": {entry['who']}")
    ]
    return {
        "who_concepts": len(extracted),
        "baseline_concepts": len(baseline),
        "ids_in_both": len(both),
        "ids_only_in_who": sorted(set(extracted) - set(baseline)),
        "ids_only_in_baseline": sorted(set(baseline) - set(extracted)),
        "name_mismatches": mismatches,
        "name_mismatches_prefixed_context": len(prefixed),
        "name_mismatches_other": len(mismatches) - len(prefixed),
        "class_mismatches": [
            {"id": concept_id, "who": extracted[concept_id].concept_class, "baseline": baseline[concept_id].concept_class}
            for concept_id in both
            if extracted[concept_id].concept_class != baseline[concept_id].concept_class
        ],
    }
