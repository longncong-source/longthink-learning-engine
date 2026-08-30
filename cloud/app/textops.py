"""Text/vector math helpers shared by repository backends (pure functions, unit-testable)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

_WORD_RE = re.compile(r"\w+", re.UNICODE)

_STOPWORDS = frozenset(
    """a an and are as at be been by for from has have in is it its of on that the
    this to was were what when where which who will with our we you your""".split()
)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def content_terms(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _STOPWORDS}


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def keyword_score(query: str, document: str) -> float:
    """F1 overlap between significant query terms and document terms (0..1)."""
    q = content_terms(query)
    d = content_terms(document)
    if not q or not d:
        return 0.0
    overlap = len(q & d)
    if overlap == 0:
        return 0.0
    precision = overlap / len(q)
    recall = overlap / len(d)
    return 2 * precision * recall / (precision + recall)


def parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def recency_score(updated_at: str | datetime, half_life_days: float, now: datetime | None = None) -> float:
    """Exponential decay: 1.0 now, 0.5 after one half-life. Never below 0."""
    now = now or datetime.now(timezone.utc)
    age_days = (now - parse_iso(updated_at)).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0
    half_life = max(half_life_days, 0.01)
    return 0.5 ** (age_days / half_life)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def combine_scores(
    semantic: float,
    keyword: float,
    importance: float,
    recency: float,
    weights: dict[str, float],
) -> float:
    """final = w_sem*semantic + w_kw*keyword + w_imp*importance + w_rec*recency (spec section 9)."""
    total = (
        weights.get("semantic", 0.0) * clamp01(semantic)
        + weights.get("keyword", 0.0) * clamp01(keyword)
        + weights.get("importance", 0.0) * clamp01(importance)
        + weights.get("recency", 0.0) * clamp01(recency)
    )
    return clamp01(total)


def normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    """Rescale weights so they sum to 1.0 when possible (keeps scores interpretable)."""
    positive = {k: max(0.0, v) for k, v in raw.items()}
    total = sum(positive.values())
    if total <= 0:
        share = 1.0 / len(positive) if positive else 0.0
        return {k: share for k in positive}
    return {k: v / total for k, v in positive.items()}


def isoformat_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def within_age(updated_at: str | datetime, days: float, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return (now - parse_iso(updated_at)) <= timedelta(days=max(days, 0.0))
