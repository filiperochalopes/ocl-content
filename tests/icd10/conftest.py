"""Fixtures for the ICD-10 pipeline tests.

Small synthetic inputs only: a compressed baseline CSV, the four DATASUS tables in a directory
(and a ZIP holding them plus a CID-O table), and a compact ClaML file that exercises the French
label variants, the roman chapter numbering, inline references, and a modifier class.
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

BASELINE_FIELDS = [
    "resource_type", "owner_id", "source", "id", "name", "description", "concept_class",
    "attr:hierarchy_level", "attr:chapter_number", "parent_concept_urls",
]
BASELINE_ROWS = [
    ("ICD-10", "ICD-10 Root Concept", "Root", "", ""),
    ("1", "Certain infectious and parasitic diseases", "Chapter", "1", "1"),
    ("22", "Codes for special purposes", "Chapter", "1", "22"),
    ("A00-A09", "Intestinal infectious diseases", "Group", "2", "1"),
    ("A00", "Cholera", "Code", "3", "1"),
    ("A00.0", "Cholera due to Vibrio cholerae 01, biovar cholerae", "Code", "4", "1"),
    ("A06.4", "Amoebic liver abscess", "Code", "4", "1"),
    ("A09", "Other gastroenteritis and colitis of infectious and unspecified origin", "Code", "3", "1"),
    ("J09", "Influenza due to identified zoonotic or pandemic influenza virus", "Code", "3", "10"),
    ("M34", "Systemic sclerosis", "Code", "3", "13"),
    ("S52.0", "Fracture of upper end of ulna", "Code", "4", "19"),
    ("U07.1", "COVID-19, virus identified", "Code", "4", "22"),
]

DATASUS_TABLES = {
    "CID-10-CAPITULOS.CSV": [
        "NUMCAP;CATINIC;CATFIM;DESCRICAO;DESCRABREV;",
        "1;A00;B99;Capítulo I - Algumas doenças infecciosas e parasitárias;I.   Algumas doenças infecciosas e parasitárias;",
        "22;U00;U99;Capítulo XXII - Códigos para propósitos especiais;XXII. Códigos para propósitos especiais;",
    ],
    "CID-10-GRUPOS.CSV": [
        "CATINIC;CATFIM;DESCRICAO;DESCRABREV;",
        "A00;A09;Doenças infecciosas intestinais;Doenças infecciosas intestinais;",
    ],
    "CID-10-CATEGORIAS.CSV": [
        "CAT;CLASSIF;DESCRICAO;DESCRABREV;REFER;EXCLUIDOS;",
        "A00;;Cólera;A00   Colera;;",
        "A09;;Diarréia e gastroenterite de origem infecciosa presumível;A09   Diarreia e gastroenterite orig infecc presum;;",
        "J09;;Influenza [gripe] devida a vírus identificado da gripe aviária;J09   Influenza dev virus gripe aviária;;",
        "12X;;Código inválido;12X;;",
    ],
    "CID-10-SUBCATEGORIAS.CSV": [
        "SUBCAT;CLASSIF;RESTRSEXO;CAUSAOBITO;DESCRICAO;DESCRABREV;REFER;EXCLUIDOS;",
        "A000;;;;Cólera devida a Vibrio cholerae 01, biótipo cholerae;A00.0 Colera dev Vibrio cholerae 01 biot cholerae;;",
        "A09;;;;Diarréia e gastroenterite de origem infecciosa presumível;A09   Diarreia e gastroenterite orig infecc presum;;",
        "U071;;;;COVID-19;U07.1 COVID-19;;",
        "A0;;;;Inválido;A0 Inválido;;",
    ],
}

CID_O_TABLE = ["CAT;DESCRICAO;REFER;", "8000/3;Neoplasia maligna;8000/3;"]

ATIH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ClaML version="2.0.0">
  <Meta name="lang" value="fr"/>
  <Title date="2024-01-01" name="CIM-10-FR" version="2024">Classification Internationale des Maladies CIM-10-FR 2024</Title>
  <Class code="I" kind="chapter">
    <Rubric kind="preferred"><Label xml:lang="fr">Certaines maladies infectieuses et parasitaires</Label></Rubric>
  </Class>
  <Class code="XXII" kind="chapter">
    <Rubric kind="preferred"><Label xml:lang="fr">Codes pour usages particuliers</Label></Rubric>
  </Class>
  <Class code="A00-A09" kind="block">
    <Rubric kind="preferred"><Label xml:lang="fr">Maladies intestinales infectieuses</Label></Rubric>
  </Class>
  <Class code="A00.0" kind="category">
    <Rubric kind="preferred"><Label xml:lang="fr">À Vibrio cholerae 01, biovar cholerae</Label></Rubric>
    <Rubric kind="inclusion"><Label xml:lang="fr">Choléra classique</Label></Rubric>
  </Class>
  <Class code="U07.1" kind="category">
    <Rubric kind="preferred"><Label variants="FM" xml:lang="fr">COVID-19</Label></Rubric>
    <Rubric kind="preferred"><Label variants="OMS" xml:lang="fr">COVID-19, virus identifié</Label></Rubric>
  </Class>
  <Class code="A06.4" kind="category">
    <Rubric kind="preferred"><Label xml:lang="fr">Abcès amibien du foie<Reference class="in brackets" usage="aster">K77.0</Reference></Label></Rubric>
  </Class>
  <Class code="U07.10" kind="category" variants="FM">
    <Rubric kind="preferred"><Label xml:lang="fr">COVID-19, forme respiratoire, virus identifié</Label></Rubric>
  </Class>
  <Class code="M34" kind="category">
    <Rubric kind="preferred"><Label xml:lang="fr">Première dénomination</Label></Rubric>
    <Rubric kind="preferred"><Label xml:lang="fr">Deuxième dénomination</Label></Rubric>
  </Class>
  <ModifierClass code="0" modifier="S01B18_5">
    <Rubric kind="preferred"><Label xml:lang="fr">phase immunotolérante</Label></Rubric>
  </ModifierClass>
</ClaML>
"""


@pytest.fixture
def baseline_csv(tmp_path: Path) -> Path:
    path = tmp_path / "baseline.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BASELINE_FIELDS)
        writer.writeheader()
        for concept_id, name, concept_class, level, chapter in BASELINE_ROWS:
            writer.writerow(
                {
                    "resource_type": "Concept",
                    "owner_id": "WHO",
                    "source": "ICD-10-WHO",
                    "id": concept_id,
                    "name": name,
                    "description": "",
                    "concept_class": concept_class,
                    "attr:hierarchy_level": level,
                    "attr:chapter_number": chapter,
                    "parent_concept_urls": "",
                }
            )
    return path


@pytest.fixture
def datasus_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "datasus"
    directory.mkdir()
    for name, rows in DATASUS_TABLES.items():
        (directory / name).write_text("\n".join(rows) + "\n", encoding="iso-8859-1")
    return directory


@pytest.fixture
def datasus_zip(tmp_path: Path, datasus_dir: Path) -> Path:
    path = tmp_path / "CID10CSV.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in DATASUS_TABLES:
            archive.write(datasus_dir / name, arcname=name)
        archive.writestr("CID-O-CATEGORIAS.CSV", "\n".join(CID_O_TABLE) + "\n")
    return path


@pytest.fixture
def atih_xml(tmp_path: Path) -> Path:
    path = tmp_path / "cim10fr2024syst_claml_20231215.xml"
    path.write_text(ATIH_XML, encoding="utf-8")
    return path


WHO_CLAML_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ClaML version="2.0.0">
  <Meta name="lang" value="en"/>
  <Title date="2020-03-22" name="ICD-10-EN" version="2019-covid-expanded">International Statistical Classification of Diseases</Title>
  <Class code="I" kind="chapter">
    <Rubric kind="preferred"><Label xml:lang="en">Certain infectious and parasitic diseases</Label></Rubric>
  </Class>
  <Class code="XXII" kind="chapter">
    <Rubric kind="preferred"><Label xml:lang="en">Codes for special purposes</Label></Rubric>
  </Class>
  <Class code="A00-A09" kind="block">
    <Rubric kind="preferred"><Label xml:lang="en">Intestinal infectious diseases</Label></Rubric>
  </Class>
  <Class code="A00" kind="category">
    <Rubric kind="preferred"><Label xml:lang="en">Cholera</Label></Rubric>
  </Class>
  <Class code="E10" kind="category">
    <ModifiedBy code="S04E10_4" />
    <Rubric kind="preferred"><Label xml:lang="en">Type 1 diabetes mellitus</Label></Rubric>
  </Class>
  <Class code="I70" kind="category">
    <ModifiedBy code="I70M10_4" />
    <Rubric kind="preferred"><Label xml:lang="en">Atherosclerosis</Label></Rubric>
  </Class>
  <Modifier code="S04E10_4"><SubClass code=".0" /><SubClass code=".9" /></Modifier>
  <ModifierClass code=".0" modifier="S04E10_4">
    <Rubric kind="preferred"><Label xml:lang="en">With coma</Label></Rubric>
  </ModifierClass>
  <ModifierClass code=".9" modifier="S04E10_4">
    <Rubric kind="preferred"><Label xml:lang="en">Without complications</Label></Rubric>
  </ModifierClass>
  <ModifierClass code="0" modifier="I70M10_4">
    <Rubric kind="preferred"><Label xml:lang="en">without gangrene</Label></Rubric>
  </ModifierClass>
  <ModifierClass code="1" modifier="I70M10_4"></ModifierClass>
</ClaML>
"""

DATASUS_XML = """<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>
<cid10 versao="V2007">
  <capitulo numcap="1" codcap="A00-B99" romano="I" inicial="A00" final="B99">
    <nome>Algumas doenças infecciosas e parasitárias</nome>
    <nome50>I.   Algumas doenças infecciosas e parasitárias</nome50>
    <grupo codgrupo="A00-A09" inicial="A00" final="A09">
      <nome>Doenças infecciosas intestinais</nome>
      <categoria codcat="A00">
        <duplaclassificacao tipo="cruz">
          <referencia codrefer="J998">J99.8*</referencia>
        </duplaclassificacao>
        <nome>Cólera</nome>
        <nome50>A00   Colera</nome50>
        <restricoes causaobito="nao" />
        <subcategoria codsubcat="A000">
          <nome>Cólera devida a Vibrio cholerae 01, biótipo cholerae</nome>
          <nome50>A00.0 Colera dev Vibrio cholerae 01 biot cholerae</nome50>
        </subcategoria>
        <subcategoria codsubcat="A009">
          <nome>Cólera não especificada</nome>
        </subcategoria>
      </categoria>
      <categoria codcat="A06">
        <nome>Abscesso hepático &cruz; amebiano</nome>
      </categoria>
    </grupo>
  </capitulo>
</cid10>
"""

DATASUS_DTD = """<!ELEMENT document (cid10)>
<!ELEMENT cid10 (capitulo+)>
<!ENTITY cruz "&#8224;">
"""


@pytest.fixture
def who_claml_zip(tmp_path: Path) -> Path:
    path = tmp_path / "icd102019en.xml.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("icd102019en.xml", WHO_CLAML_XML)
    return path


@pytest.fixture
def datasus_xml_zip(tmp_path: Path) -> Path:
    path = tmp_path / "CID10XML.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("CID10.xml", DATASUS_XML.encode("iso-8859-1"))
        archive.writestr("CID10.dtd", DATASUS_DTD)
        archive.writestr("CID-O.xml", "<document/>")
    return path


@pytest.fixture
def datasus_xml_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "datasus-xml"
    directory.mkdir()
    (directory / "CID10.xml").write_bytes(DATASUS_XML.encode("iso-8859-1"))
    (directory / "CID10.dtd").write_text(DATASUS_DTD, encoding="utf-8")
    return directory
