"""Text extraction for supported document types (spec section 31): PDF, DOCX, TXT, Markdown.

Heavy parsers are imported lazily so the core API keeps working without them.
PDF page numbers are preserved for source citation (spec section 32).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from cloud.app.errors import (
    DependencyMissingError,
    UnsupportedMediaTypeError,
    ValidationError,
)

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

SUPPORTED_EXTENSIONS = frozenset(_MIME_BY_EXT)


@dataclass(slots=True)
class ExtractedPage:
    number: int | None  # None => unpaginated source
    text: str


@dataclass(slots=True)
class Extraction:
    pages: list[ExtractedPage]
    mime_type: str
    meta: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    def is_empty(self) -> bool:
        return not self.full_text.strip()


def detect_mime(filename: str) -> str:
    from pathlib import PurePosixPath

    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    return _MIME_BY_EXT.get(suffix, "application/octet-stream")


def _extract_txt_md(filename: str, data: bytes) -> Extraction:
    text = data.decode("utf-8", errors="replace")
    return Extraction(
        pages=[ExtractedPage(number=1, text=text)],
        mime_type=detect_mime(filename),
        meta={"pages": 1},
    )


def _extract_pdf(filename: str, data: bytes) -> Extraction:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DependencyMissingError(
            "pypdf is not installed - run: pip install -r cloud/requirements-documents.txt",
            details={"extension": ".pdf"},
        ) from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [
            ExtractedPage(number=index + 1, text=(page.extract_text() or ""))
            for index, page in enumerate(reader.pages)
        ]
    except Exception as exc:  # noqa: BLE001 - malformed PDFs surface as validation errors
        raise ValidationError(f"Cannot parse PDF '{filename}': {exc}") from exc
    return Extraction(
        pages=pages,
        mime_type=detect_mime(filename),
        meta={"pages": len(pages)},
    )


def _extract_docx(filename: str, data: bytes) -> Extraction:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise DependencyMissingError(
            "python-docx is not installed - run: pip install -r cloud/requirements-documents.txt",
            details={"extension": ".docx"},
        ) from exc
    try:
        document = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in document.paragraphs]
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Cannot parse DOCX '{filename}': {exc}") from exc
    return Extraction(
        pages=[ExtractedPage(number=1, text="\n".join(paragraphs))],
        mime_type=detect_mime(filename),
        meta={"pages": 1},
    )


_EXTRACTORS = {
    ".txt": _extract_txt_md,
    ".md": _extract_txt_md,
    ".markdown": _extract_txt_md,
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
}


def extract_pages(filename: str, data: bytes) -> Extraction:
    """Dispatch by extension. Raises UnsupportedMediaTypeError for unknown types."""
    from pathlib import PurePosixPath

    suffix = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    extractor = _EXTRACTORS.get(suffix)
    if extractor is None:
        raise UnsupportedMediaTypeError(
            f"Unsupported document type '{suffix or '(none)'}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            details={"filename": filename},
        )
    extraction = extractor(filename, data)
    if extraction.is_empty():
        raise ValidationError(
            f"No extractable text found in '{filename}'. "
            "Scanned/image-only PDFs need OCR before ingestion.",
            details={"filename": filename},
        )
    return extraction
