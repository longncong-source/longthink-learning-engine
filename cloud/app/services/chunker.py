"""Semantic-aware chunking for document ingestion (spec section 31).

Strategy:
  - split text into paragraphs first; merge paragraphs up to CHUNK_SIZE chars
  - oversized paragraphs are split on sentence boundaries (hard-wrap fallback)
  - each following chunk carries a sentence-tail of the previous one as overlap
Page mapping stays exact because chunking runs per extracted page (spec section 32).
"""

from __future__ import annotations

import re

_PARA_SPLIT = re.compile(r"\n\s*\n")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def _split_by_sentences(paragraph: str, size: int) -> list[str]:
    sentences = [s.strip() for s in _SENT_SPLIT.split(paragraph) if s.strip()]
    if not sentences:
        return [paragraph[i:i + size] for i in range(0, len(paragraph), size)]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= size:
            current += " " + sentence
        else:
            pieces.append(current)
            current = sentence
        while len(current) > size:  # pathological single long sentence -> hard slice
            pieces.append(current[:size])
            current = current[size:]
    if current:
        pieces.append(current)
    return pieces


def _tail_sentences(text: str, max_chars: int) -> str:
    if max_chars <= 0 or not text:
        return ""
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    tail: list[str] = []
    budget = max_chars
    for sentence in reversed(sentences):
        if len(sentence) <= budget:
            tail.insert(0, sentence)
            budget -= len(sentence) + 2
        else:
            break
    return "\n\n".join(tail)


def chunk_page_text(text: str, size_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    """Chunk one page of text. Returns [] for blank pages."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size_chars:
        return [text]

    paragraphs = [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= size_chars:
            units.append(paragraph)
        else:
            units.extend(_split_by_sentences(paragraph, size_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + 2 + len(unit) <= size_chars:
            current += "\n\n" + unit
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)

    if overlap_chars > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for previous, chunk in zip(chunks, chunks[1:]):
            tail = _tail_sentences(previous, overlap_chars)
            overlapped.append((tail + "\n\n" + chunk).strip() if tail else chunk)
        return overlapped
    return chunks


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~4 chars/token). Good enough for stats."""
    return max(1, len(text or "") // 4)
