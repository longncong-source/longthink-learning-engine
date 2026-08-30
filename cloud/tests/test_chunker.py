"""Unit tests: semantic-aware chunker (spec section 31)."""

from __future__ import annotations

import pytest

from cloud.app.services.chunker import chunk_page_text, estimate_tokens


def _para(words: int, marker: str) -> str:
    return f"{marker} " + " ".join(f"word{i}" for i in range(words))


class TestChunkPageText:
    def test_short_text_single_chunk(self):  # type: ignore[no-untyped-def]
        chunks = chunk_page_text("Short paragraph about vendor delays.", size_chars=200, overlap_chars=0)
        assert chunks == ["Short paragraph about vendor delays."]

    def test_empty_returns_empty(self):  # type: ignore[no-untyped-def]
        assert chunk_page_text("", 100, 10) == []
        assert chunk_page_text("   \n\n  ", 100, 10) == []

    def test_paragraphs_merged_up_to_size(self):  # type: ignore[no-untyped-def]
        text = "\n\n".join(_para(20, f"P{i}") for i in range(6))
        chunks = chunk_page_text(text, size_chars=600, overlap_chars=0)
        assert all(len(c) <= 600 for c in chunks)
        assert "".join(text.split()).startswith(chunks[0].split()[0])

    def test_oversized_paragraph_split_on_sentences(self):  # type: ignore[no-untyped-def]
        long_para = ". ".join(f"Sentence number {i} talks about procurement" for i in range(60)) + "."
        chunks = chunk_page_text(long_para, size_chars=400, overlap_chars=0)
        assert len(chunks) >= 2
        assert all(len(c) <= 400 for c in chunks)

    def test_overlap_carries_tail_of_previous(self):  # type: ignore[no-untyped-def]
        text = "\n\n".join(_para(30, f"Block{i}. Final sentence here.") for i in range(8))
        chunks = chunk_page_text(text, size_chars=350, overlap_chars=120)
        assert len(chunks) > 1
        # overlap makes consecutive chunks share content
        first_words = set(chunks[1].split()[:5])
        assert first_words & set(chunks[0].split())

    def test_deterministic(self):  # type: ignore[no-untyped-def]
        text = "\n\n".join(_para(40, f"S{i}") for i in range(5))
        assert chunk_page_text(text, 500, 100) == chunk_page_text(text, 500, 100)


class TestTokenEstimate:
    def test_positive_and_scaled(self):  # type: ignore[no-untyped-def]
        assert estimate_tokens("") >= 1
        assert estimate_tokens("x" * 400) == pytest.approx(100)
