"""Read the DATASUS CID-10 XML and emit ``pt_BR`` name candidates.

This is the second Brazilian input, and it is **not** ClaML: it is a DATASUS-specific format whose
root is ``cid10`` with a ``versao`` attribute (``V2007``, while the download page is V2008 — both
values are recorded, neither is "corrected"). It is ISO-8859-1 and it uses entities declared only
in the ``CID10.dtd`` shipped in the same archive (``&cruz;`` → ``†``).

Entity handling is therefore explicit and closed: the text entities are read from the shipped DTD
and substituted, and any entity that is neither a built-in nor declared by that DTD is an error.
Nothing here expands external or recursive entities.

Codes follow the same rules as the CSV adapter — ``numcap`` for a chapter, ``codgrupo`` for a
group, ``codcat`` for a category, and a four-character ``codsubcat`` gaining its separator
(``A000`` → ``A00.0``) with the original kept as ``source_code``. ``duplaclassificacao``
(cross/asterisk) and ``restricoes`` (sex, cause-of-death) are not names and are ignored; the
CID-O and tabulation members of the archive belong to other classifications and are counted only.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from ..model import LOCALE_PT_BR, AdapterResult, NameCandidate

AUTHORITY = "DATASUS"
EDITION = "CID-10 (DATASUS V2008 page; root attribute versao=V2007)"
ENCODING = "iso-8859-1"
XML_MEMBER = "CID10.xml"
DTD_MEMBER = "CID10.dtd"
OUT_OF_SCOPE_MEMBERS = ("CID-O.xml", "Listas.xml", "CID-O.dtd", "Listas.dtd")
BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
ENTITY_DECL = re.compile(r"<!ENTITY\s+([A-Za-z_][\w.\-]*)\s+[\"']([^\"']*)[\"']\s*>")
ENTITY_REF = re.compile(r"&(#\d+|#x[0-9A-Fa-f]+|[A-Za-z_][\w.\-]*);")
CODE_3 = re.compile(r"^[A-Z]\d{2}$")
GROUP = re.compile(r"^[A-Z]\d{2}-[A-Z]\d{2}$")

KIND_MAP = {"capitulo": "chapter", "grupo": "group", "categoria": "category", "subcategoria": "subcategory"}


def read_members(source: Path) -> tuple[str, str, list[str]]:
    """Return ``(xml text, dtd text, out-of-scope members)`` from a ZIP, directory, or XML file."""
    source = Path(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = {Path(info.filename).name: info.filename for info in archive.infolist() if not info.is_dir()}
            if XML_MEMBER not in members:
                raise ValueError(f"{source}: no {XML_MEMBER} inside the archive")
            xml_text = archive.read(members[XML_MEMBER]).decode(ENCODING)
            dtd_text = archive.read(members[DTD_MEMBER]).decode(ENCODING) if DTD_MEMBER in members else ""
            out_of_scope = sorted(name for name in members if name in OUT_OF_SCOPE_MEMBERS)
        return xml_text, dtd_text, out_of_scope
    if source.is_dir():
        xml_path = source / XML_MEMBER
        if not xml_path.is_file():
            raise ValueError(f"{source}: no {XML_MEMBER} in the directory")
        dtd_path = source / DTD_MEMBER
        out_of_scope = sorted(name for name in OUT_OF_SCOPE_MEMBERS if (source / name).is_file())
        return (
            xml_path.read_bytes().decode(ENCODING),
            dtd_path.read_bytes().decode(ENCODING) if dtd_path.is_file() else "",
            out_of_scope,
        )
    if source.is_file():
        return source.read_bytes().decode(ENCODING), "", []
    raise ValueError(f"expected CID10XML.zip, a directory, or CID10.xml: {source}")


def resolve_entities(xml_text: str, dtd_text: str, source: str) -> tuple[str, dict[str, str]]:
    """Substitute only the text entities declared in the shipped DTD, then reject the rest."""
    declarations = {name: value for name, value in ENTITY_DECL.findall(dtd_text)}
    if "SYSTEM" in dtd_text or "PUBLIC" in dtd_text:
        external = [name for name in re.findall(r"<!ENTITY\s+([A-Za-z_][\w.\-]*)\s+(?:SYSTEM|PUBLIC)", dtd_text)]
        if external:
            raise ValueError(f"{source}: refusing external entity declaration(s): {', '.join(external)}")
    resolved = xml_text
    for name, value in declarations.items():
        resolved = resolved.replace(f"&{name};", value)
    unknown = sorted(
        {
            match.group(1)
            for match in ENTITY_REF.finditer(resolved)
            if not match.group(1).startswith("#") and match.group(1) not in BUILTIN_ENTITIES
        }
    )
    if unknown:
        raise ValueError(
            f"{source}: entity reference(s) not declared by the shipped DTD: {', '.join('&' + name + ';' for name in unknown)}"
        )
    return resolved, declarations


def candidates(source: Path, *, locale: str = LOCALE_PT_BR) -> AdapterResult:
    result = AdapterResult(authority=AUTHORITY, locale=locale, edition=EDITION)
    xml_text, dtd_text, out_of_scope = read_members(Path(source))
    resolved, declarations = resolve_entities(xml_text, dtd_text, str(source))
    result.stats["entities_declared"] = declarations
    result.stats["out_of_scope_members"] = out_of_scope
    try:
        root = ET.fromstring(resolved)
    except ET.ParseError as error:
        raise ValueError(f"{source}: not well-formed XML: {error}") from None
    if root.tag != "cid10":
        raise ValueError(f"{source}: expected a cid10 root element, found {root.tag!r}")
    result.stats["versions"] = root.get("versao")
    result.stats["counts"] = {}

    for chapter in root.findall("capitulo"):
        _emit(result, locale, "chapter", _own_text(chapter, "nome"), chapter.get("numcap"), chapter)
        for group in chapter.findall("grupo"):
            _walk_group(result, locale, group)
        for category in chapter.findall("categoria"):
            _emit_category(result, locale, category)

    result.candidates, duplicates = _deduplicate(result.candidates)
    result.stats["duplicate_identical_rows"] = duplicates
    return result


def _walk_group(result: AdapterResult, locale: str, group: ET.Element) -> None:
    _emit(result, locale, "group", _own_text(group, "nome"), group.get("codgrupo"), group)
    for nested in group.findall("grupo"):
        _walk_group(result, locale, nested)
    for category in group.findall("categoria"):
        _emit_category(result, locale, category)


def _emit_category(result: AdapterResult, locale: str, category: ET.Element) -> None:
    _emit(result, locale, "category", _own_text(category, "nome"), category.get("codcat"), category)
    for subcategory in category.findall("subcategoria"):
        _emit(result, locale, "subcategory", _own_text(subcategory, "nome"), subcategory.get("codsubcat"), subcategory)


def _own_text(element: ET.Element, child_name: str) -> str:
    child = element.find(child_name)
    return (child.text or "").strip() if child is not None else ""


def _emit(result: AdapterResult, locale: str, kind: str, label: str, raw_code: str | None, element: ET.Element) -> None:
    counts = result.stats["counts"]
    counts[kind] = counts.get(kind, 0) + 1
    raw = (raw_code or "").strip()
    if not label:
        result.skip("blank-label", kind=kind, source_code=raw)
        return
    if kind == "chapter":
        if not raw.isdigit():
            result.skip("chapter-number-not-numeric", kind=kind, source_code=raw)
            return
        code = str(int(raw))
    elif kind == "group":
        if not GROUP.match(raw):
            result.skip("invalid-group-range", kind=kind, source_code=raw)
            return
        code = raw
    elif kind == "category":
        if not CODE_3.match(raw):
            result.skip("invalid-category-code", kind=kind, source_code=raw)
            return
        code = raw
    else:
        letters = raw.replace(".", "")
        if len(letters) == 4 and CODE_3.match(letters[:3]) and letters[3].isdigit():
            code = f"{letters[:3]}.{letters[3]}"
        elif len(letters) == 3 and CODE_3.match(letters):
            code = letters
        else:
            result.skip("invalid-subcategory-code", kind=kind, source_code=raw)
            return
    result.candidates.append(
        NameCandidate(
            code=code,
            locale=locale,
            label=label,
            authority=AUTHORITY,
            edition=EDITION,
            kind=kind,
            source_file=XML_MEMBER,
            source_code=raw,
            source_row=0,
        )
    )


def _deduplicate(candidates: list[NameCandidate]) -> tuple[list[NameCandidate], int]:
    kept: list[NameCandidate] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for candidate in candidates:
        key = (candidate.code, candidate.label)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        kept.append(candidate)
    return kept, duplicates
