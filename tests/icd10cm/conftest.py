"""Synthetic FY27 ICD-10-CM Tabular XML and order-file fixtures."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

XML = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<ICD10CM.tabular>
  <version>2027</version>
  <chapter>
    <name>1</name>
    <desc>Certain infectious and parasitic diseases (A00-B99)</desc>
    <section id="A00-A99"><desc>Editorial intestinal range (A00-A99)</desc><notes><note>Applies to the contained sections.</note></notes></section>
    <section id="A00-A09">
      <desc>Intestinal infectious diseases (A00-A09)</desc>
      <diag>
        <name>A00</name><desc>Cholera</desc>
        <diag><name>A00.0</name><desc>Cholera due to Vibrio cholerae</desc></diag>
      </diag>
    </section>
    <section id="B10"><desc>Other human herpesviruses (B10)</desc><diag><name>B10</name><desc>Other human herpesviruses</desc></diag></section>
  </chapter>
  <chapter>
    <name>19</name>
    <desc>Injury, poisoning and certain other consequences of external causes (S00-T88)</desc>
    <section id="S00-S59"><desc>Editorial-free structural range (S00-S59)</desc></section>
    <section id="S52-S59">
      <desc>Injuries to the forearm (S52-S59)</desc>
      <diag><name>S52.521</name><desc>Torus fracture of lower end of right radius</desc><sevenChrDef><extension char=\"A\">initial encounter</extension></sevenChrDef></diag>
    </section>
  </chapter>
</ICD10CM.tabular>
"""


def order_line(number: int, code: str, valid: int, short: str, long: str) -> str:
    return f"{number:05d} {code:<7} {valid} {short:<60} {long}\r\n"


@pytest.fixture
def fy27_zip(tmp_path) -> Path:
    path = tmp_path / "icd10cm-table-and-index-2027.zip"
    order = "".join([
        order_line(1, "A00", 0, "Cholera", "Cholera"),
        order_line(2, "A000", 1, "Cholera due to Vibrio", "Cholera due to Vibrio cholerae"),
        order_line(3, "B10", 0, "Other human herpes", "Other human herpesviruses"),
        order_line(4, "S52521", 0, "Torus fracture lower radius", "Torus fracture of lower end of right radius"),
        order_line(5, "S52521A", 1, "Torus fracture initial", "Torus fracture of lower end of right radius, initial encounter"),
    ])
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("icd10cm-table-and-index-2027/icd10cm-tabular_-2027.xml", XML)
        archive.writestr("icd10cm-code-descriptions-2027/icd10cm-order-2027.txt", order)
    return path
