"""Read the ATIH CIM-10-FR ClaML and emit ``fr`` name candidates.

The file is the **French national edition** of ICD-10 (CIM-10-FR, ATIH), not a translation of
the WHO English release, and it carries two label families through ``variants``: ``OMS`` (the
WHO wording) and ``FM`` (the French PMSI wording). For a name that is added to the WHO-aligned
OCL Source this adapter therefore uses the ``OMS`` preferred label when both exist, records the
variant it used, and treats an ``FM``-only label as a candidate flagged for review. A code with
several preferred labels and no ``OMS`` label is refused with a reason rather than guessed.

Two normalizations are applied and recorded, never silent:

* a chapter ``Class`` uses a roman numeral; it is converted to the integer chapter number used
  by the canonical baseline and flagged ``chapter-roman-normalized``;
* a preferred ``Label`` that also contains a nested ``Reference`` (the cross/asterisk pointer)
  contributes only its own text — the reference code is not part of the name — and is flagged
  ``inline-markup``.

``Modifier``/``ModifierClass`` codes model post-coordination and are not concept names: they are
counted and skipped. Inclusion, exclusion, coding-hint and other rubrics are not synonyms and
are not emitted. A document with an internal DTD subset or an entity declaration is refused:
the shipped French file carries an external ``<!DOCTYPE ClaML SYSTEM "ClaML.dtd">``, which
ElementTree does not resolve, but internal entities would be expanded and are not needed here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import LOCALE_FR, AdapterResult, NameCandidate
from ..xmlsafe import parse_claml

AUTHORITY = "ATIH"
EDITION = "CIM-10-FR 2024 (2024-01-01)"
ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18,
    "XIX": 19, "XX": 20, "XXI": 21, "XXII": 22,
}
PREFERRED = "preferred"
WHO_VARIANT = "OMS"
NATIONAL_VARIANT = "FM"


def candidates(path: Path, *, locale: str = LOCALE_FR) -> AdapterResult:
    path = Path(path)
    result = AdapterResult(authority=AUTHORITY, locale=locale, edition=EDITION)
    root = _parse(path)
    result.stats["title"] = _title(root)
    result.stats["declared_lang"] = next(
        (meta.get("value") for meta in root.findall("Meta") if meta.get("name") == "lang"), None
    )
    result.stats["classes"] = 0
    result.stats["modifier_classes"] = len(root.findall("ModifierClass"))
    result.stats["kinds"] = {}
    for code_holder in root.findall("ModifierClass"):
        result.skip("modifier-class", source_code=code_holder.get("code") or "")
    for class_element in root.findall("Class"):
        result.stats["classes"] += 1
        kind = class_element.get("kind") or "unknown"
        result.stats["kinds"][kind] = result.stats["kinds"].get(kind, 0) + 1
        source_code = (class_element.get("code") or "").strip()
        candidate, reason = _candidate(class_element, kind, source_code, locale, path.name)
        if candidate is None:
            result.skip(reason, source_code=source_code, kind=kind)
            continue
        result.candidates.append(candidate)
    return result


def _parse(path: Path) -> ET.Element:
    return parse_claml(Path(path))


def _title(root: ET.Element) -> dict[str, str | None]:
    title = root.find("Title")
    if title is None:
        return {}
    return {"name": title.get("name"), "version": title.get("version"), "date": title.get("date")}


def _candidate(
    class_element: ET.Element,
    kind: str,
    source_code: str,
    locale: str,
    source_file: str,
) -> tuple[NameCandidate | None, str]:
    rubrics = [rubric for rubric in class_element.findall("Rubric") if rubric.get("kind") == PREFERRED]
    if not rubrics:
        return None, "no-preferred-label"
    labels: list[ET.Element] = [label for rubric in rubrics for label in rubric.findall("Label")]
    if not labels:
        return None, "preferred-rubric-without-label"
    flags: list[str] = []
    who = [label for label in labels if (label.get("variants") or "") == WHO_VARIANT]
    if who:
        chosen = who[0]
        flags.append("variant-OMS")
        if len(labels) > 1:
            flags.append("variant-selected-from-multiple")
    elif len(labels) == 1:
        chosen = labels[0]
        if (chosen.get("variants") or "") == NATIONAL_VARIANT:
            flags.append("variant-FM")
    else:
        return None, "conflicting-preferred-labels-without-OMS"
    label = _label_text(chosen)
    if not label:
        return None, "blank-label"
    if list(chosen):
        flags.append("inline-markup")
    if kind == "chapter":
        number = ROMAN.get(source_code.upper())
        if number is None:
            return None, "unrecognized-chapter-numeral"
        code = str(number)
        flags.append("chapter-roman-normalized")
    else:
        code = source_code
    if not code:
        return None, "blank-code"
    return (
        NameCandidate(
            code=code,
            locale=locale,
            label=label,
            authority=AUTHORITY,
            edition=EDITION,
            kind=kind,
            source_file=source_file,
            source_code=source_code,
            source_row=0,
            variant=(chosen.get("variants") or None),
            flags=tuple(flags),
        ),
        "",
    )


def _label_text(label: ET.Element) -> str:
    """The label's own text only; a nested reference pointer is not part of the name."""
    return (label.text or "").strip()
