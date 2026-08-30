"""Unit tests: pure scoring/text helpers used by hybrid search (spec sections 9, 36)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cloud.app.textops import (
    combine_scores,
    cosine_similarity,
    keyword_score,
    normalize_weights,
    recency_score,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 0.0, 1.0], [1.0, 0.0, 1.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_mismatched_lengths_safe(self):
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector_safe(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestKeywordScore:
    def test_exact_term_overlap_beats_unrelated(self):
        query = "vendor mechanical drawing delay"
        relevant = "Vendor A caused a mechanical drawing approval delay of 21 days."
        irrelevant = "Office lunch menu includes pizza on Friday."
        assert keyword_score(query, relevant) > keyword_score(query, irrelevant)

    def test_perfect_overlap_is_one(self):
        assert keyword_score("delay", "delay report") == pytest.approx(2 / 3)

    def test_stopwords_ignored(self):
        assert keyword_score("the delay of the vendor", "delay vendor") == pytest.approx(1.0)

    def test_empty_inputs(self):
        assert keyword_score("", "") == 0.0
        assert keyword_score("query", "") == 0.0


class TestRecencyScore:
    def test_now_is_one(self):
        now = datetime.now(timezone.utc)
        assert recency_score(now, 30) == pytest.approx(1.0)

    def test_one_half_life_is_half(self):
        created = datetime.now(timezone.utc) - timedelta(days=30)
        assert recency_score(created, 30.0) == pytest.approx(0.5, rel=1e-3)

    def test_future_clamped_to_one(self):
        future = datetime.now(timezone.utc) + timedelta(days=5)
        assert recency_score(future, 30) == pytest.approx(1.0)

    def test_accepts_iso_string(self):
        created = datetime.now(timezone.utc) - timedelta(days=60)
        assert recency_score(created.isoformat(), 30.0) == pytest.approx(0.25, rel=1e-3)


class TestCombineScores:
    def test_spec_default_weights(self):
        total = combine_scores(
            semantic=1.0,
            keyword=1.0,
            importance=1.0,
            recency=1.0,
            weights={"semantic": 0.6, "keyword": 0.2, "importance": 0.1, "recency": 0.1},
        )
        assert total == pytest.approx(1.0)

    def test_semantic_dominates_with_spec_weights(self):
        high_semantic = combine_scores(
            1.0, 0.0, 0.0, 0.0,
            {"semantic": 0.6, "keyword": 0.2, "importance": 0.1, "recency": 0.1},
        )
        high_keyword = combine_scores(
            0.0, 1.0, 0.0, 0.0,
            {"semantic": 0.6, "keyword": 0.2, "importance": 0.1, "recency": 0.1},
        )
        assert high_semantic > high_keyword

    def test_values_clamped(self):
        total = combine_scores(
            semantic=99.0,
            keyword=-5.0,
            importance=0.5,
            recency=0.5,
            weights={"semantic": 0.6, "keyword": 0.2, "importance": 0.1, "recency": 0.1},
        )
        assert 0.0 <= total <= 1.0


class TestNormalizeWeights:
    def test_sums_to_one(self):
        normalized = normalize_weights({"a": 0.6, "b": 0.3, "c": 0.05, "d": 0.05})
        assert sum(normalized.values()) == pytest.approx(1.0)

    def test_all_zero_fallback(self):
        normalized = normalize_weights({"a": 0.0, "b": 0.0})
        assert sum(normalized.values()) == pytest.approx(1.0)

    def test_negative_clamped(self):
        normalized = normalize_weights({"a": -1.0, "b": 1.0})
        assert normalized["a"] == 0.0
        assert normalized["b"] == pytest.approx(1.0)
