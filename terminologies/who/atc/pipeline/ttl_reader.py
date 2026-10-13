"""Narrow, deliberately limited Turtle reading for the WHO ATC ontology as published on BioPortal.

This is **not** a general RDF/Turtle parser. It reads exactly the block shape BioPortal's UMLS2RDF
exporter produces for this ontology: one blank-line-separated paragraph per ``owl:Class``, each
predicate on its own tab-indented line, e.g.::

    <http://purl.bioontology.org/ontology/ATC/A> a owl:Class ;
        skos:prefLabel <triple-quote>ALIMENTARY TRACT AND METABOLISM DRUGS<triple-quote>@en ;
        skos:notation <triple-quote>A<triple-quote>^^xsd:string ;
        skos:altLabel <triple-quote>ALIMENTARY TRACT AND METABOLISM<triple-quote>@en ;
        rdfs:subClassOf owl:Thing ;
        <http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> <triple-quote>1<triple-quote>^^xsd:string ;
        <http://purl.bioontology.org/ontology/ATC/IS_DRUG_CLASS> <triple-quote>Y<triple-quote>^^xsd:string ;
        umls:cui <triple-quote>C3653992<triple-quote>^^xsd:string ;
        umls:tui <triple-quote>T121<triple-quote>^^xsd:string ;
        umls:hasSTY <http://purl.bioontology.org/ontology/STY/T121> ;
     .

   (``<triple-quote>`` above stands for a literal ``\"\"\"``, not spelled out here so it cannot
   terminate this docstring early.)

The same export also carries the 127 UMLS Semantic Type classes under a different namespace
(``.../ontology/STY/...``, one-line single-quoted literals instead of triple-quoted ones); those are
not ATC codes and are skipped and counted separately. Reading this narrowly (regex over one
paragraph at a time, like ``xmlsafe.py`` does for the ICD-10 ClaML adapters) keeps the pipeline free
of a third-party RDF dependency; see ``tests/atc/test_ttl_reader.py`` for the shapes this is checked
against, including the exact live fields of concept ``A`` in ``WHO/WHOATC`` verified on 2026-10-12.

Field set and level-to-class mapping mirror the sibling ``ciel-scripts`` repository's
``ocl_uploader_whoatc.py`` (read via ``rdflib`` there); this module is read-only reference material,
not imported from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ATC_NS = "http://purl.bioontology.org/ontology/ATC/"
STY_NS = "http://purl.bioontology.org/ontology/STY/"

_SUBJECT_RE = re.compile(r'^<' + re.escape(ATC_NS) + r'([^>]+)>\s+a\s+owl:Class\s*;', re.MULTILINE)
_PREF_LABEL_RE = re.compile(r'skos:prefLabel\s+"""(.*?)"""@en\s*;', re.DOTALL)
_ALT_LABEL_RE = re.compile(r'skos:altLabel\s+"""(.*?)"""@en\s*;', re.DOTALL)
_SUBCLASS_RE = re.compile(r'rdfs:subClassOf\s+(?:<' + re.escape(ATC_NS) + r'([^>]+)>|owl:Thing)\s*;')
_LEVEL_RE = re.compile(r'<' + re.escape(ATC_NS) + r'ATC_LEVEL>\s+"""(\d)"""\^\^xsd:string\s*;')
_IS_DRUG_CLASS_RE = re.compile(r'<' + re.escape(ATC_NS) + r'IS_DRUG_CLASS>\s+"""(\w)"""\^\^xsd:string\s*;')
_CUI_RE = re.compile(r'umls:cui\s+"""(.*?)"""\^\^xsd:string\s*;')
_HAS_STY_RE = re.compile(r'umls:hasSTY\s+<' + re.escape(STY_NS) + r'([^>]+)>\s*;')
_VERSION_RE = re.compile(r'owl:versionInfo\s+"([^"]+)"')
_SOURCE_RE = re.compile(r'dcterms:source\s+"([^"]+)"')


@dataclass(frozen=True)
class AtcClass:
    """One ATC code read from the ontology, with every field verbatim except the level→int cast."""

    code: str
    title: str
    alt_label: str | None
    level: int
    parent: str | None  # None only for level 1 (``rdfs:subClassOf owl:Thing``)
    cui: str | None
    semantic_types: tuple[str, ...]
    is_drug_class: str | None  # "Y" / "N" when the file states it; None when absent (level 5 usually)
    source_block: int


@dataclass
class AtcOntology:
    version_info: str  # e.g. "2025_02_10", the BioPortal submission's own `owl:versionInfo`
    umls_source: str  # e.g. "UMLS 2025AB"
    classes: list[AtcClass] = field(default_factory=list)
    skipped_semantic_types: int = 0
    duplicate_codes: list[str] = field(default_factory=list)


def _blocks(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text)


def read(path: Path) -> AtcOntology:
    """Read a BioPortal ATC Turtle export into ordered ``AtcClass`` rows."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"ATC Turtle file not found: {path}")
    text = path.read_text(encoding="utf-8")

    version_match = _VERSION_RE.search(text)
    if not version_match:
        raise ValueError(f"{path}: no owl:versionInfo found; this does not look like the ATC ontology export")
    source_match = _SOURCE_RE.search(text)
    ontology = AtcOntology(
        version_info=version_match.group(1),
        umls_source=source_match.group(1) if source_match else "",
    )

    seen: set[str] = set()
    for number, block in enumerate(_blocks(text), start=1):
        block = block.strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0]
        if f"<{STY_NS}" in first_line:
            ontology.skipped_semantic_types += 1
            continue
        subject_match = _SUBJECT_RE.match(block)
        if not subject_match:
            continue  # the ontology header paragraph, or anything that is not an owl:Class block
        code = subject_match.group(1)

        pref_label = _PREF_LABEL_RE.search(block)
        if not pref_label:
            raise ValueError(f"{path}: block {number} ({code}) has no skos:prefLabel")
        level_match = _LEVEL_RE.search(block)
        if not level_match:
            raise ValueError(f"{path}: block {number} ({code}) has no ATC_LEVEL")
        alt_label = _ALT_LABEL_RE.search(block)
        subclass_match = _SUBCLASS_RE.search(block)
        parent = subclass_match.group(1) if subclass_match and subclass_match.group(1) else None
        cui_match = _CUI_RE.search(block)
        is_drug_class_match = _IS_DRUG_CLASS_RE.search(block)

        if code in seen:
            ontology.duplicate_codes.append(code)
        seen.add(code)

        ontology.classes.append(
            AtcClass(
                code=code,
                title=pref_label.group(1).strip(),
                alt_label=alt_label.group(1).strip() if alt_label else None,
                level=int(level_match.group(1)),
                parent=parent,
                cui=cui_match.group(1).strip() if cui_match else None,
                semantic_types=tuple(_HAS_STY_RE.findall(block)),
                is_drug_class=is_drug_class_match.group(1) if is_drug_class_match else None,
                source_block=number,
            )
        )
    return ontology
