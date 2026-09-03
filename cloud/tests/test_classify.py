"""Unit tests for rule-based knowledge-domain recognition (real filenames)."""

from __future__ import annotations

import pytest

from cloud.app.services.classify import classify_knowledge_type as classify

CASES = [
    # (filename, expected)
    ("231375-06-DAS-009-DS for Pressure Differential Tranmitters-Rev.0.pdf", "engineering"),
    ("231375-EL06-M23-001_General Arrangement Drawings_Rev.B.pdf", "engineering"),
    ("231375-06-TRD-003_TRD for Shutdown Valves_Rev.0.pdf", "engineering"),
    ("Instrument_Loop_Diagrams.pdf", "engineering"),
    ("Draft Final Report.pdf", "engineering"),
    ("SPC-0804.02-91.03 Rev D3 Environment Specification.pdf", "engineering"),
    ("LSX 182.23 LPG Tank Thi Vai_ITP Documents.pdf", "method"),
    ("231375-IN03-Q18-001_NDE Procedures REV. 0_NC.pdf", "method"),
    ("231375-EL01-P01-001_FAT Procedure (PTSC comment).pdf", "method"),
    ("231375-EL06-R01-201 - Installation Operation and Maintenance Manual(IOM) for Ex JB.pdf", "method"),
    ("231375-IN03-Q04-001_Inspection and Test Plan REV.0_NC.pdf", "method"),
    ("231375-IN02-C10-001-Monthly Progress Reports-C.pdf", "site"),
    ("SPC-0804.02-99.03 Rev D2 Shop inspection.pdf", "site"),
    ("231375-IN08-Q05-001_Inspection and Test Reports (Item 26)_Rev.A.pdf", "site"),
    ("lec15.pdf", "lesson"),
    ("Industrial InstrumentationWeek12.pdf", "lesson"),
    ("flow_measurement_2.pdf", "lesson"),
    ("13_de thi_tu dong hoa.pdf", "lesson"),
    ("question_bank.pdf", "lesson"),
    ("Transmittal 231375-PTSC-PVG-TMT-187.pdf", "document"),
    ("231375-08-COM-KVT-019_Comment sheet.pdf", "document"),
    ("231375-EL06-G13-001_Packing List (Shipment 01- Cable Gland)_Rev.A.pdf", "document"),
    ("231375-EL06-Q66-001_Certificate of Conformity (Item 26)_Rev.A.pdf", "document"),
    ("don-kien-nghi-cua-tap-the_2411134637.docx", "document"),
    ("Code_Digest_2008.pdf", "standard"),
    ("SPC-0804.02-91.04 Rev D2 HSE Legislation.pdf", "standard"),
    ("TSGN001 - Hazardous Area Classification - Guidance Notes.pdf", "standard"),
    ("s8-15.pdf", None),
    ("405.pdf", None),
    ("D1X_en.pdf", None),
]


@pytest.mark.parametrize("filename,expected", CASES)
def test_classify_real_filenames(filename, expected):  # type: ignore[no-untyped-def]
    assert classify(filename) == expected


def test_folder_shortcut_wins():  # type: ignore[no-untyped-def]
    assert classify("random.pdf", "watch:methods/random.pdf") == "method"
    assert classify("random.pdf", "knowledge/lessons/random.pdf") == "lesson"


def test_empty_returns_none():  # type: ignore[no-untyped-def]
    assert classify("") is None
    assert classify(None) is None
