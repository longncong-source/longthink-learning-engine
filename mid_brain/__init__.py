"""Mid Brain - Intelligence Layer between First Brain (Experience) and Second Brain (Knowledge)."""

from __future__ import annotations

__version__ = "1.0.0"

from mid_brain.agent.agent_manager import AgentManager
from mid_brain.confidence.confidence_engine import ConfidenceEngine
from mid_brain.conflict.conflict_engine import ConflictEngine
from mid_brain.core.cognitive_orchestrator import CognitiveOrchestrator
from mid_brain.core.mid_brain import MidBrain, MidBrainConfig
from mid_brain.feedback.feedback_event import (
    FeedbackBus,
    FeedbackEvent,
    FeedbackSource,
    FeedbackType,
)
from mid_brain.knowledge.knowledge_manager import KnowledgeManager
from mid_brain.learning.learning_engine import LearningEngine
from mid_brain.memory.memory_manager import MemoryManager
from mid_brain.network.adaptive_network import AdaptiveCognitiveNetwork
from mid_brain.planning.planning_engine import PlanningEngine
from mid_brain.reasoning.reasoning_engine import ReasoningEngine
from mid_brain.reference.reference_engine import ReferenceEngine
from mid_brain.reflection.reflection_engine import ReflectionEngine

__all__ = [
    "MidBrain",
    "MidBrainConfig",
    "CognitiveOrchestrator",
    "MemoryManager",
    "KnowledgeManager",
    "ReasoningEngine",
    "LearningEngine",
    "ConflictEngine",
    "ReferenceEngine",
    "ReflectionEngine",
    "PlanningEngine",
    "AgentManager",
    "ConfidenceEngine",
    "AdaptiveCognitiveNetwork",
    "FeedbackBus",
    "FeedbackEvent",
    "FeedbackType",
    "FeedbackSource",
]
