"""One adapter per national edition; each emits name candidates and its own skip reasons."""

from . import atih_claml, datasus_csv, datasus_xml, who_claml

__all__ = ["atih_claml", "datasus_csv", "datasus_xml", "who_claml"]
