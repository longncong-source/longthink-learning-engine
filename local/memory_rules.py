"""First Brain memory typing rules (spec section 13).

Leaf module on purpose: both :mod:`local.agent` and :mod:`local.consolidation`
import from here, so neither depends on the other.
"""

from __future__ import annotations

import re

_DECISION_RE = re.compile(
    r"\b(decide[sd]?|decision|approve[d]?|approval|rule|policy|quy\u1ebft \u0111\u1ecbnh|quy t\u1eafc)\b",
    re.IGNORECASE,
)
_LESSON_RE = re.compile(
    r"\b(lessons? learned?|lesson|pitfall|mistake|never again|b\u00e0i h\u1ecdc)\b",
    re.IGNORECASE,
)
_EPISODIC_RE = re.compile(
    r"\b(delay(ed)?|late|missed|happened|occurred|slipped|\d+\s*(day|week|month)s?)\b",
    re.IGNORECASE,
)
_TEMP_RE = re.compile(r"\b(temp|temporary|todo|scratch|draft only|t\u1ea1m)\b", re.IGNORECASE)


def classify_memory(text: str) -> tuple[str, float]:
    """Deterministic memory typing + importance heuristic (spec section 13)."""
    if _DECISION_RE.search(text):
        return "decision", 0.75
    if _LESSON_RE.search(text):
        return "lesson", 0.70
    if _EPISODIC_RE.search(text):
        return "episodic", 0.65
    return "semantic", 0.50


def is_long_term_worthy(text: str, importance: float = 0.0) -> bool:
    if _TEMP_RE.search(text):
        return False
    if _DECISION_RE.search(text) or _LESSON_RE.search(text):
        return True
    return importance >= 0.60
