"""Mid Brain Reasoning Engine - Compare, synthesize, evaluate evidence, calculate confidence."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


@dataclass(slots=True)
class ComparisonResult:
    """Result of comparing two answers."""
    similarity: float
    key_differences: list[str]
    agreements: list[str]
    first_brain_unique: list[str]
    second_brain_unique: list[str]


@dataclass(slots=True)
class EvidenceEvaluation:
    """Result of evidence evaluation."""
    first_brain_support: float
    second_brain_support: float
    mid_brain_support: float
    contradicting_evidence: list[str]
    supporting_evidence: list[str]
    evidence_quality: str  # high, medium, low


@dataclass(slots=True)
class ConfidenceBreakdown:
    """Explainable confidence breakdown."""
    first_brain_weight: float
    second_brain_weight: float
    evidence_weight: float
    consistency_weight: float
    historical_weight: float
    source_reliability_weight: float
    final_confidence: float
    explanation: str


@dataclass(slots=True)
class SynthesisResult:
    """Result of answer synthesis."""
    answer: str
    key_points: list[str]
    sources_used: list[str]
    confidence: float
    reasoning: str


class ReasoningEngine:
    """
    Reasoning Engine for Mid Brain.

    Capabilities:
    - Compare answers from First and Second Brain
    - Evaluate evidence
    - Calculate explainable confidence
    - Synthesize final answers
    """

    def __init__(self, mid_brain: MidBrain) -> None:
        self.mid_brain = mid_brain
        self._initialized = False

    def initialize(self) -> None:
        """Initialize reasoning engine."""
        self._initialized = True

    def compare_answers(
        self,
        first_brain_answer: str | None,
        second_brain_answer: str | None,
        question: str,
    ) -> dict[str, Any]:
        """Compare answers from both brains."""
        if not first_brain_answer and not second_brain_answer:
            return asdict(ComparisonResult(
                similarity=0.0,
                key_differences=["No answers available"],
                agreements=[],
                first_brain_unique=[],
                second_brain_unique=[],
            ))

        if not first_brain_answer:
            return asdict(ComparisonResult(
                similarity=0.0,
                key_differences=["Only Second Brain answered"],
                agreements=[],
                first_brain_unique=[],
                second_brain_unique=[second_brain_answer[:200]],
            ))

        if not second_brain_answer:
            return asdict(ComparisonResult(
                similarity=0.0,
                key_differences=["Only First Brain answered"],
                agreements=[],
                first_brain_unique=[first_brain_answer[:200]],
                second_brain_unique=[],
            ))

        # Simple text comparison
        fb_tokens = set(re.findall(r"\w+", first_brain_answer.lower()))
        sb_tokens = set(re.findall(r"\w+", second_brain_answer.lower()))

        if not fb_tokens and not sb_tokens:
            similarity = 0.0
        else:
            intersection = fb_tokens & sb_tokens
            union = fb_tokens | sb_tokens
            similarity = len(intersection) / len(union) if union else 0.0

        # Extract key differences (simplified)
        fb_unique = fb_tokens - sb_tokens
        sb_unique = sb_tokens - fb_tokens
        agreements = list(intersection)

        return asdict(ComparisonResult(
            similarity=similarity,
            key_differences=[
                f"First Brain unique terms: {', '.join(list(fb_unique)[:10])}" if fb_unique else "None",
                f"Second Brain unique terms: {', '.join(list(sb_unique)[:10])}" if sb_unique else "None",
            ],
            agreements=agreements[:20],
            first_brain_unique=list(fb_unique)[:20],
            second_brain_unique=list(sb_unique)[:20],
        ))

    def evaluate_evidence(
        self,
        first_brain_answer: str | None,
        second_brain_answer: str | None,
        recall_result: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate supporting evidence from all sources."""
        # Count evidence sources
        mid_brain_results = recall_result.get("results", [])
        mid_brain_count = len(mid_brain_results)

        # Simple heuristic evaluation
        fb_support = 0.5 if first_brain_answer else 0.0
        sb_support = 0.5 if second_brain_answer else 0.0
        mb_support = min(mid_brain_count * 0.1, 1.0)

        # Check for contradictions in conflicts
        contradicting = [c.get("claim_a", "") for c in conflicts] if conflicts else []
        supporting = []

        # Add mid-brain memories as supporting evidence
        for r in mid_brain_results[:5]:
            supporting.append(f"Mid Brain: {r.get('content', '')[:100]}")

        quality = "high" if (fb_support + sb_support + mb_support) > 1.5 else "medium" if (fb_support + sb_support + mb_support) > 0.5 else "low"

        return asdict(EvidenceEvaluation(
            first_brain_support=fb_support,
            second_brain_support=sb_support,
            mid_brain_support=mb_support,
            contradicting_evidence=contradicting,
            supporting_evidence=supporting,
            evidence_quality=quality,
        ))

    def calculate_confidence(
        self,
        evidence: dict[str, Any],
        conflicts: list[dict[str, Any]],
        first_brain_answer: str | None,
        second_brain_answer: str | None,
    ) -> float:
        """Calculate explainable confidence score (0.0 - 1.0)."""
        # Weights for different factors
        weights = {
            "first_brain": 0.20,
            "second_brain": 0.25,
            "evidence": 0.25,
            "consistency": 0.15,
            "historical": 0.10,
            "source_reliability": 0.05,
        }

        # Factor scores (0.0 - 1.0)
        fb_score = 1.0 if first_brain_answer else 0.0
        sb_score = 1.0 if second_brain_answer else 0.0

        # Evidence score based on quality
        eq = evidence.get("evidence_quality", "low")
        evidence_score = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(eq, 0.3)

        # Consistency: lower if conflicts detected
        consistency_score = max(0.0, 1.0 - len(conflicts) * 0.3)

        # Historical: placeholder (would use past validation success rate)
        historical_score = 0.7

        # Source reliability: placeholder
        source_reliability_score = 0.8

        # Weighted sum
        final_confidence = (
            weights["first_brain"] * fb_score +
            weights["second_brain"] * sb_score +
            weights["evidence"] * evidence_score +
            weights["consistency"] * consistency_score +
            weights["historical"] * historical_score +
            weights["source_reliability"] * source_reliability_score
        )

        # Clamp
        final_confidence = max(0.0, min(1.0, final_confidence))

        return round(final_confidence, 3)

    def explain_confidence(
        self,
        evidence: dict[str, Any],
        conflicts: list[dict[str, Any]],
        first_brain_answer: str | None,
        second_brain_answer: str | None,
        confidence: float,
    ) -> str:
        """Generate human-readable explanation of confidence."""
        parts = []

        if first_brain_answer:
            parts.append("First Brain provided an answer")
        else:
            parts.append("First Brain did not answer")

        if second_brain_answer:
            parts.append("Second Brain provided an answer")
        else:
            parts.append("Second Brain did not answer")

        eq = evidence.get("evidence_quality", "low")
        parts.append(f"Evidence quality: {eq}")

        if conflicts:
            parts.append(f"{len(conflicts)} conflict(s) detected")
        else:
            parts.append("No conflicts detected")

        parts.append(f"Final confidence: {confidence:.2f}")

        return "; ".join(parts)

    def synthesize(
        self,
        question: str,
        first_brain_answer: str | None,
        second_brain_answer: str | None,
        comparison: dict[str, Any],
        evidence: dict[str, Any],
        confidence: float,
    ) -> dict[str, Any]:
        """Synthesize final answer from all sources."""
        # Determine best answer based on confidence and availability
        answers = []
        sources = []

        if second_brain_answer and evidence.get("second_brain_support", 0) > 0.4:
            answers.append(second_brain_answer)
            sources.append("Second Brain (Knowledge)")

        if first_brain_answer and evidence.get("first_brain_support", 0) > 0.4:
            answers.append(first_brain_answer)
            sources.append("First Brain (Experience)")

        # If we have mid-brain memories, use them
        # (In full implementation, would retrieve and incorporate)

        if not answers:
            answer = "I could not find sufficient information to answer this question."
            reasoning = "No reliable sources available"
        elif len(answers) == 1:
            answer = answers[0]
            reasoning = f"Based on {sources[0]}"
        else:
            # Multiple answers - synthesize
            if comparison.get("similarity", 0) > 0.7:
                answer = answers[0]  # They agree
                reasoning = f"Both brains agree: {', '.join(sources)}"
            else:
                # They differ - present both with caveats
                answer = "Different perspectives found:\n\n"
                for i, (ans, src) in enumerate(zip(answers, sources, strict=True), 1):
                    answer += f"{i}. [{src}] {ans}\n\n"
                answer += f"\nConfidence: {confidence:.2f} - Consider verifying independently."
                reasoning = f"Conflicting answers from {', '.join(sources)}"

        return asdict(SynthesisResult(
            answer=answer.strip(),
            key_points=[],  # Would extract key points in full impl
            sources_used=sources,
            confidence=confidence,
            reasoning=reasoning,
        ))
