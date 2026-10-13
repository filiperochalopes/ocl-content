"""Fixtures for the WHO-ATC pipeline tests: a small synthetic ATC Turtle export and alterations page.

The Turtle fixture exercises: a level-1 chapter (``rdfs:subClassOf owl:Thing``), a level-2 group, a
level-5 substance with no ``IS_DRUG_CLASS`` predicate (mirrors the live file), a ``skos:altLabel``,
multiple ``umls:hasSTY`` values, and the 127-semantic-type-class shape (here just two, under the
``STY`` namespace, single-quoted) that must be skipped rather than read as ATC codes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SYNTHETIC_TTL = '''
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix umls: <http://bioportal.bioontology.org/ontologies/umls/> .

<http://purl.bioontology.org/ontology/ATC/>
    a owl:Ontology ;
    rdfs:comment "RDF Version of the UMLS ontology ATC" ;
    rdfs:label "Anatomical Therapeutic Chemical Classification System" ;
    owl:versionInfo "2099_01_01" ;
    dcterms:source "UMLS 2099AB" ;
    skos:altLabel "ATC" .

<http://purl.bioontology.org/ontology/ATC/A> a owl:Class ;
\tskos:prefLabel """ALIMENTARY TRACT AND METABOLISM DRUGS"""@en ;
\tskos:notation """A"""^^xsd:string ;
\tskos:altLabel """ALIMENTARY TRACT AND METABOLISM"""@en ;
\trdfs:subClassOf owl:Thing ;
\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """1"""^^xsd:string ;
\t<http://purl.bioontology.org/ontology/ATC/IS_DRUG_CLASS> """Y"""^^xsd:string ;
\tumls:cui """C3653992"""^^xsd:string ;
\tumls:hasSTY <http://purl.bioontology.org/ontology/STY/T121> ;
 .

<http://purl.bioontology.org/ontology/ATC/A01> a owl:Class ;
\tskos:prefLabel """STOMATOLOGICAL PREPARATIONS"""@en ;
\tskos:notation """A01"""^^xsd:string ;
\trdfs:subClassOf <http://purl.bioontology.org/ontology/ATC/A> ;
\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """2"""^^xsd:string ;
\t<http://purl.bioontology.org/ontology/ATC/IS_DRUG_CLASS> """Y"""^^xsd:string ;
\tumls:cui """C0282273"""^^xsd:string ;
\tumls:hasSTY <http://purl.bioontology.org/ontology/STY/T121> ;
 .

<http://purl.bioontology.org/ontology/ATC/A01AD02> a owl:Class ;
\tskos:prefLabel """benzydamine"""@en ;
\tskos:notation """A01AD02"""^^xsd:string ;
\trdfs:subClassOf <http://purl.bioontology.org/ontology/ATC/A01AD> ;
\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """5"""^^xsd:string ;
\tumls:cui """C0005032"""^^xsd:string ;
\tumls:hasSTY <http://purl.bioontology.org/ontology/STY/T121> ;
\tumls:hasSTY <http://purl.bioontology.org/ontology/STY/T109> ;
 .

<http://purl.bioontology.org/ontology/ATC/A01AD> a owl:Class ;
\tskos:prefLabel """Other agents for local oral treatment"""@en ;
\tskos:notation """A01AD"""^^xsd:string ;
\trdfs:subClassOf <http://purl.bioontology.org/ontology/ATC/A01A> ;
\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """4"""^^xsd:string ;
\t<http://purl.bioontology.org/ontology/ATC/IS_DRUG_CLASS> """Y"""^^xsd:string ;
 .

<http://purl.bioontology.org/ontology/ATC/A01A> a owl:Class ;
\tskos:prefLabel """STOMATOLOGICAL PREPARATIONS"""@en ;
\tskos:notation """A01A"""^^xsd:string ;
\trdfs:subClassOf <http://purl.bioontology.org/ontology/ATC/A01> ;
\t<http://purl.bioontology.org/ontology/ATC/ATC_LEVEL> """3"""^^xsd:string ;
\t<http://purl.bioontology.org/ontology/ATC/IS_DRUG_CLASS> """Y"""^^xsd:string ;
 .

<http://purl.bioontology.org/ontology/STY/T121> a owl:Class ;
\tskos:notation "T121"^^xsd:string ;
\tskos:prefLabel "Pharmacologic Substance"@en .

<http://purl.bioontology.org/ontology/STY/T109> a owl:Class ;
\tskos:notation "T109"^^xsd:string ;
\tskos:prefLabel "Organic Chemical"@en .
'''

ALTERATIONS_HTML = """
<html><body>
<table border="0" cellpadding="0" cellspacing="0"><tr>
<th valign="top"><a href="./?order_by=0">Previous&nbsp;ATC&nbsp;code</a></th>
<th valign="top"><a href="./?order_by=1">Substance name</a></th>
<th valign="top"><a href="./?order_by=2">New&nbsp;ATC&nbsp;code</a></th>
<th valign="top"><a href="./?order_by=3">Year changed</a></th>
</tr>
<tr valign="top" class="rowbg0"><td colspan="1"></td></tr>
<tr valign="top" class="rowbg1"><td>A01AD02&nbsp;<sup><a href="#n27_1" title="27) footnote">27)</a></sup></td><td>benzydamine HCl </td><td>R02AX03</td><td colspan="1">2018
</td></tr>
<tr valign="top" class="rowbg0"><td>A03AE02</td><td>tegaserod</td><td>A06AX06</td><td colspan="1">2013
</td></tr>
</table>
</body></html>
"""


@pytest.fixture
def ttl_path(tmp_path) -> Path:
    path = tmp_path / "ATC.ttl"
    path.write_text(SYNTHETIC_TTL, encoding="utf-8")
    return path


@pytest.fixture
def alterations_path(tmp_path) -> Path:
    path = tmp_path / "atc_alterations_cumulative.html"
    path.write_text(ALTERATIONS_HTML, encoding="utf-8")
    return path
