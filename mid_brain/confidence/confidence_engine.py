"""Confidence Engine for Mid Brain - Explainable confidence scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ConfidenceFactor:
    """A single factor contributing to confidence."""

    name: str
    weight: float
    score: float  # 0.0 to 1.0
    explanation: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConfidenceReport:
    """Complete confidence assessment with explanation."""

    overall_confidence: float
    level: str  # UNKNOWN, WEAK, POSSIBLE, STRONG, HIGHLY_RELIABLE, VERIFIED
    factors: list[ConfidenceFactor]
    methodology: str
    limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class ConfidenceEngine:
    """
    Explainable confidence engine for Mid Brain.

    Confidence Levels:
    - 0.00 UNKNOWN
    - 0.25 WEAK
    - 0.50 POSSIBLE
    - 0.75 STRONG
    - 0.90 HIGHLY_RELIABLE
    - 0.99 VERIFIED
    """

    # Weight configuration for different evidence sources
    DEFAULT_WEIGHTS = {
        "first_brain_support": 0.25,
        "second_brain_support": 0.25,
        "mid_brain_memory_support": 0.15,
        "evidence_quality": 0.15,
        "consistency": 0.10,
        "human_confirmation": 0.10,
    }

    LEVEL_THRESHOLDS = {
        "UNKNOWN": 0.00,
        "WEAK": 0.25,
        "POSSIBLE": 0.50,
        "STRONG": 0.75,
        "HIGHLY_RELIABLE": 0.90,
        "VERIFIED": 0.99,
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self._normalize_weights()

    def initialize(self) -> None:
        """Initialize the confidence engine."""
        pass

    def _normalize_weights(self) -> None:
        """Normalize weights to sum to 1.0."""
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def calculate(
        self,
        evidence: dict[str, Any],
        conflicts: list[dict[str, Any]] | None = None,
        first_brain_answer: str | None = None,
        second_brain_answer: str | None = None,
        mid_brain_memories: list[dict[str, Any]] | None = None,
        human_confirmed: bool = False,
    ) -> ConfidenceReport:
        """
        Calculate explainable confidence score.

        Args:
            evidence: Evidence dictionary from reasoning engine
            conflicts: List of detected conflicts
            first_brain_answer: Answer from First Brain
            second_brain_answer: Answer from Second Brain
            mid_brain_memories: Relevant Mid Brain memories
            human_confirmed: Whether human has confirmed
        """
        factors = []

        # Factor 1: First Brain Support
        fb_score = self._score_first_brain(evidence, first_brain_answer)
        factors.append(ConfidenceFactor(
            name="first_brain_support",
            weight=self.weights.get("first_brain_support", 0.25),
            score=fb_score,
            explanation=self._explain_first_brain(fb_score, first_brain_answer),
            evidence=[first_brain_answer] if first_brain_answer else [],
        ))

        # Factor 2: Second Brain Support
        sb_score = self._score_second_brain(evidence, second_brain_answer)
        factors.append(ConfidenceFactor(
            name="second_brain_support",
            weight=self.weights.get("second_brain_support", 0.25),
            score=sb_score,
            explanation=self._explain_second_brain(sb_score, second_brain_answer),
            evidence=[second_brain_answer] if second_brain_answer else [],
        ))

        # Factor 3: Mid Brain Memory Support
        mb_score = self._score_mid_brain_memory(mid_brain_memories or [])
        factors.append(ConfidenceFactor(
            name="mid_brain_memory_support",
            weight=self.weights.get("mid_brain_memory_support", 0.15),
            score=mb_score,
            explanation=self._explain_mid_brain_memory(mb_score, mid_brain_memories or []),
            evidence=[m.get("content", "")[:100] for m in (mid_brain_memories or [])[:3]],
        ))

        # Factor 4: Evidence Quality
        eq_score = self._score_evidence_quality(evidence)
        factors.append(ConfidenceFactor(
            name="evidence_quality",
            weight=self.weights.get("evidence_quality", 0.15),
            score=eq_score,
            explanation=self._explain_evidence_quality(eq_score, evidence),
            evidence=list(evidence.keys()),
        ))

        # Factor 5: Consistency (no conflicts)
        conf_penalty = len(conflicts or []) * 0.15
        consistency_score = max(0.0, 1.0 - conf_penalty)
        factors.append(ConfidenceFactor(
            name="consistency",
            weight=self.weights.get("consistency", 0.10),
            score=consistency_score,
            explanation=self._explain_consistency(consistency_score, conflicts or []),
            evidence=[c.get("claim_a", "")[:50] for c in (conflicts or [])[:3]],
        ))

        # Factor 6: Human Confirmation
        hc_score = 1.0 if human_confirmed else 0.0
        factors.append(ConfidenceFactor(
            name="human_confirmation",
            weight=self.weights.get("human_confirmation", 0.10),
            score=hc_score,
            explanation="Human has confirmed this answer" if human_confirmed else "No human confirmation",
            evidence=["Human approval"] if human_confirmed else [],
        ))

        # Calculate weighted confidence
        confidence = sum(f.weight * f.score for f in factors)
        confidence = max(0.0, min(1.0, confidence))

        # Apply conflict penalty
        if conflicts:
            for conflict in conflicts:
                severity = conflict.get("severity", "medium")
                penalty = {"low": 0.05, "medium": 0.15, "high": 0.30, "critical": 0.50}.get(severity, 0.15)
                confidence = max(0.0, confidence - penalty)

        level = self._get_level(confidence)

        # Generate methodology description
        methodology = self._generate_methodology(factors, conflicts)

        # Generate limitations
        limitations = self._generate_limitations(factors, conflicts, first_brain_answer, second_brain_answer)

        # Generate recommendations
        recommendations = self._generate_recommendations(factors, confidence, conflicts)

        return ConfidenceReport(
            overall_confidence=confidence,
            level=level,
            factors=factors,
            methodology=methodology,
            limitations=limitations,
            recommendations=recommendations,
        )

    def _score_first_brain(self, evidence: dict[str, Any], answer: str | None) -> float:
        """Score First Brain contribution."""
        if not answer:
            return 0.0

        support = evidence.get("first_brain_support", 0.5)
        if isinstance(support, (int, float)):
            return max(0.0, min(1.0, float(support)))

        # Heuristic based on answer quality
        if len(answer) < 10:
            return 0.2
        if len(answer) < 50:
            return 0.5
        return 0.7

    def _score_second_brain(self, evidence: dict[str, Any], answer: str | None) -> float:
        """Score Second Brain contribution."""
        if not answer:
            return 0.0

        support = evidence.get("second_brain_support", 0.5)
        if isinstance(support, (int, float)):
            return max(0.0, min(1.0, float(support)))

        if len(answer) < 10:
            return 0.2
        if len(answer) < 50:
            return 0.5
        return 0.7

    def _score_mid_brain_memory(self, memories: list[dict[str, Any]]) -> float:
        """Score Mid Brain memory relevance."""
        if not memories:
            return 0.0

        # Score based on number and relevance of memories
        count = len(memories)
        if count >= 5:
            return 0.9
        elif count >= 3:
            return 0.7
        elif count >= 1:
            return 0.5
        return 0.0

    def _score_evidence_quality(self, evidence: dict[str, Any]) -> float:
        """Score overall evidence quality."""
        quality = evidence.get("evidence_quality", "medium")
        if isinstance(quality, str):
            return {"high": 1.0, "medium": 0.6, "low": 0.3}.get(quality, 0.5)

        # Check for specific quality indicators
        score = 0.5
        if evidence.get("citations"):
            score += 0.2
        if evidence.get("sources"):
            score += 0.1
        if evidence.get("verifiable"):
            score += 0.2
        return min(1.0, score)

    def _explain_first_brain(self, score: float, answer: str | None) -> str:
        if not answer:
            return "No answer from First Brain (Experience)"
        if score >= 0.7:
            return "First Brain provided detailed, relevant experience"
        if score >= 0.5:
            return "First Brain provided relevant but limited experience"
        return "First Brain answer is brief or lacks detail"

    def _explain_second_brain(self, score: float, answer: str | None) -> str:
        if not answer:
            return "No answer from Second Brain (Knowledge)"
        if score >= 0.7:
            return "Second Brain provided comprehensive knowledge"
        if score >= 0.5:
            return "Second Brain provided relevant knowledge"
        return "Second Brain answer is brief or lacks detail"

    def _explain_mid_brain_memory(self, score: float, memories: list[dict[str, Any]]) -> str:
        if not memories:
            return "No relevant Mid Brain memories found"
        if score >= 0.7:
            return f"Strong support from {len(memories)} relevant memories"
        if score >= 0.5:
            return f"Moderate support from {len(memories)} memories"
        return f"Weak support from {len(memories)} memories"

    def _explain_evidence_quality(self, score: float, evidence: dict[str, Any]) -> str:
        if score >= 0.8:
            return "High-quality evidence with citations and verifiable sources"
        if score >= 0.5:
            return "Moderate evidence quality"
        return "Limited or low-quality evidence"

    def _explain_consistency(self, score: float, conflicts: list[dict[str, Any]]) -> str:
        if not conflicts:
            return "No conflicts detected between sources"
        if score >= 0.8:
            return f"Minor conflicts ({len(conflicts)}) with low severity"
        return f"Significant conflicts ({len(conflicts)}) detected"

    def _get_level(self, confidence: float) -> str:
        for level, threshold in reversed(list(self.LEVEL_THRESHOLDS.items())):
            if confidence >= threshold:
                return level
        return "UNKNOWN"

    def _generate_methodology(self, factors: list[ConfidenceFactor], conflicts: list[dict[str, Any]]) -> str:
        parts = ["Confidence calculated using weighted factors:"]
        for f in factors:
            parts.append(f"  - {f.name}: {f.weight:.0%} weight × {f.score:.2f} = {f.weight * f.score:.3f}")
        if conflicts:
            parts.append(f"Conflict penalty applied: {len(conflicts)} conflicts detected")
        return "\n".join(parts)

    def _generate_limitations(
        self,
        factors: list[ConfidenceFactor],
        conflicts: list[dict[str, Any]],
        fb_answer: str | None,
        sb_answer: str | None,
    ) -> list[str]:
        limitations = []

        if not fb_answer:
            limitations.append("First Brain (Experience) did not provide an answer")
        if not sb_answer:
            limitations.append("Second Brain (Knowledge) did not provide an answer")

        low_factors = [f for f in factors if f.score < 0.4]
        for f in low_factors:
            limitations.append(f"Low {f.name.replace('_', ' ')}: {f.explanation}")

        if conflicts:
            limitations.append(f"{len(conflicts)} unresolved conflicts may affect reliability")

        if all(f.score < 0.5 for f in factors):
            limitations.append("All evidence sources provide weak support")

        return limitations

    def _generate_recommendations(
        self,
        factors: list[ConfidenceFactor],
        confidence: float,
        conflicts: list[dict[str, Any]],
    ) -> list[str]:
        recommendations = []

        if confidence < 0.5:
            recommendations.append("Seek additional evidence from both brains")
            recommendations.append("Consider human review before acting on this answer")

        if conflicts:
            recommendations.append("Resolve conflicts through evidence gathering or human mediation")

        weak_factors = [f for f in factors if f.score < 0.5 and f.weight > 0.1]
        for f in weak_factors:
            if f.name == "first_brain_support":
                recommendations.append("Gather more experiential data for this topic")
            elif f.name == "second_brain_support":
                recommendations.append("Research external knowledge sources")
            elif f.name == "mid_brain_memory_support":
                recommendations.append("Build more relevant memories in Mid Brain")

        if not any(f.name == "human_confirmation" and f.score > 0 for f in factors):
            recommendations.append("Obtain human confirmation for critical decisions")

        return recommendations
