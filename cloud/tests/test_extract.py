"""Extraction dispatch tests: TXT/MD inline; PDF/DOCX via lazy deps (spec section 31)."""

from __future__ import annotations

import sys

import pytest

from cloud.app.errors import (
    DependencyMissingError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from cloud.app.services.extract import detect_mime, extract_pages


class TestTxtMd:
    def test_markdown_roundtrip(self):  # type: ignore[no-untyped-def]
        data = b"# Brief\n\nVendor drawings rule applies."
        extraction = extract_pages("brief.md", data)
        assert extraction.pages[0].number == 1
        assert "vendor drawings" in extraction.full_text.lower()
        assert extraction.mime_type == "text/markdown"

    def test_txt_replacement_decode_never_crashes(self):  # type: ignore[no-untyped-def]
        extraction = extract_pages("notes.txt", b"\xff\xfe invalid utf8 but fine")
        assert extraction.pages[0].text


class TestGuards:
    def test_unsupported_extension_415(self):  # type: ignore[no-untyped-def]
        with pytest.raises(UnsupportedMediaTypeError):
            extract_pages("payload.exe", b"MZ...")

    def test_no_extension_415(self):  # type: ignore[no-untyped-def]
        with pytest.raises(UnsupportedMediaTypeError):
            extract_pages("README", b"content")

    def test_empty_text_422(self):  # type: ignore[no-untyped-def]
        with pytest.raises(ValidationError):
            extract_pages("empty.md", b"")

    def test_blank_pdf_422_guard(self):  # type: ignore[no-untyped-def]
        pypdf = pytest.importorskip("pypdf")
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        import io

        buffer = io.BytesIO()
        writer.write(buffer)
        with pytest.raises(ValidationError):
            extract_pages("blank.pdf", buffer.getvalue())

    def test_missing_docx_dependency_message(self, monkeypatch):  # type: ignore[no-untyped-def]
        monkeypatch.setitem(sys.modules, "docx", None)  # forces ImportError on import
        with pytest.raises(DependencyMissingError):
            extract_pages("spec.docx", b"PK\x03\x04 not really a docx")


class TestMimeDetection:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("a.pdf", "application/pdf"),
            ("B.TXT", "text/plain"),
            ("c.markdown", "text/markdown"),
        ],
    )
    def test_mapping(self, filename, expected):  # type: ignore[no-untyped-def]
        assert detect_mime(filename) == expected
