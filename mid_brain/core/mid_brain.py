"""Mid Brain Core - Main entry point and orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from mid_brain.agent.agent_manager import AgentManager
from mid_brain.confidence.confidence_engine import ConfidenceEngine
from mid_brain.conflict.conflict_engine import ConflictEngine
from mid_brain.core.cognitive_orchestrator import CognitiveOrchestrator
from mid_brain.feedback.feedback_event import FeedbackBus, get_feedback_bus
from mid_brain.knowledge.knowledge_manager import KnowledgeManager
from mid_brain.learning.learning_engine import LearningEngine
from mid_brain.memory.memory_manager import MemoryManager
from mid_brain.network.adaptive_network import AdaptiveCognitiveNetwork
from mid_brain.planning.planning_engine import PlanningEngine
from mid_brain.reasoning.reasoning_engine import ReasoningEngine
from mid_brain.reference.reference_engine import ReferenceEngine
from mid_brain.reflection.reflection_engine import ReflectionEngine

if TYPE_CHECKING:
    from mid_brain.api.first_brain_adapter import FirstBrainAdapter
    from mid_brain.api.second_brain_adapter import SecondBrainAdapter
    from mid_brain.obsidian.sync_manager import SyncManager

__version__ = "1.0.0"


@dataclass(slots=True)
class MidBrainConfig:
    """Configuration for Mid Brain — phân định tổng hợp First(long-term) vs Second(short-term online) → Human Knowledge Interface."""
    first_brain_url: str = "http://127.0.0.1:8100"
    first_brain_api_key: str = "dev-local-key"
    second_brain_url: str = "http://127.0.0.1:8100"
    second_brain_api_key: str = "dev-local-key"
    # First = LONG-TERM local (duy nhất bền vững), Second = SHORT-TERM online (OpenClaw/ChatGPT/Gemini, TTL)
    enable_reflection: bool = True
    enable_learning: bool = True
    enable_conflict_detection: bool = True
    enable_reference: bool = True
    enable_planning: bool = True
    enable_agent: bool = True
    enable_confidence: bool = True
    enable_network: bool = True
    enable_obsidian: bool = False
    obsidian_vault_path: str = ""
    confidence_threshold: float = 0.62  # tối ưu thông minh: cao hơn 0.5 để bắt buộc Human quyết khi nghi ngờ
    short_term_ttl_days: int = 7
    second_brain_provider: str = "openclaw"  # openclaw | chatgpt | gemini


@dataclass(slots=True)
class MidBrainStatus:
    """Mid Brain health/status information."""
    initialized: bool = False
    uptime_seconds: float = 0.0
    components: dict[str, bool] = field(default_factory=dict)
    last_error: str | None = None


class MidBrain:
    """
    Mid Brain - The Intelligence Layer.

    Architecture:
    FIRST BRAIN (Experience) ⟷ MID BRAIN (Intelligence) ⟷ SECOND BRAIN (Knowledge)

    Responsibilities:
    - Orchestrate communication between First and Second Brain
    - Maintain independent memory (Working, Episodic, Semantic, Procedural, Strategic, Meta)
    - Knowledge validation, promotion, and versioning
    - Reasoning, conflict detection, confidence scoring
    - Reflection, learning, and future reference
    - Planning and agent execution
    - Adaptive cognitive network
    """

    def __init__(self, config: MidBrainConfig | None = None) -> None:
        self.config = config or MidBrainConfig()
        self._start_time = time.time()
        self._status = MidBrainStatus()
        self._initialized = False

        # Core components (lazy initialized)
        self._orchestrator: CognitiveOrchestrator | None = None
        self._memory_manager: MemoryManager | None = None
        self._knowledge_manager: KnowledgeManager | None = None
        self._reasoning_engine: ReasoningEngine | None = None
        self._learning_engine: LearningEngine | None = None
        self._conflict_engine: ConflictEngine | None = None
        self._reference_engine: ReferenceEngine | None = None
        self._reflection_engine: ReflectionEngine | None = None
        self._planning_engine: PlanningEngine | None = None
        self._agent_manager: AgentManager | None = None
        self._confidence_engine: ConfidenceEngine | None = None
        self._adaptive_network: AdaptiveCognitiveNetwork | None = None
        self._obsidian_sync: SyncManager | None = None
        self._feedback_bus: FeedbackBus | None = None

        # Adapters for First/Second Brain communication
        self._first_brain_adapter = None
        self._second_brain_adapter = None

    # ------------------------------------------------------------------ properties

    @property
    def first_brain(self) -> FirstBrainAdapter:
        """Get or create First Brain adapter."""
        if self._first_brain_adapter is None:
            from mid_brain.api.first_brain_adapter import FirstBrainAdapter
            self._first_brain_adapter = FirstBrainAdapter(
                base_url=self.config.first_brain_url,
                api_key=self.config.first_brain_api_key,
            )
            self._first_brain_adapter.initialize()
        return self._first_brain_adapter

    @property
    def second_brain(self) -> SecondBrainAdapter:
        """Get or create Second Brain adapter."""
        if self._second_brain_adapter is None:
            from mid_brain.api.second_brain_adapter import SecondBrainAdapter
            self._second_brain_adapter = SecondBrainAdapter(
                base_url=self.config.second_brain_url,
                api_key=self.config.second_brain_api_key,
            )
            self._second_brain_adapter.initialize()
        return self._second_brain_adapter

    @property
    def orchestrator(self) -> CognitiveOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = CognitiveOrchestrator(self)
        return self._orchestrator

    @property
    def memory(self) -> MemoryManager:
        if self._memory_manager is None:
            self._memory_manager = MemoryManager()
        return self._memory_manager

    @property
    def knowledge(self) -> KnowledgeManager:
        if self._knowledge_manager is None:
            self._knowledge_manager = KnowledgeManager(self)
        return self._knowledge_manager

    @property
    def reasoning(self) -> ReasoningEngine:
        if self._reasoning_engine is None:
            self._reasoning_engine = ReasoningEngine(self)
        return self._reasoning_engine

    @property
    def learning(self) -> LearningEngine:
        if self._learning_engine is None:
            self._learning_engine = LearningEngine(self)
        return self._learning_engine

    @property
    def conflict(self) -> ConflictEngine:
        if self._conflict_engine is None:
            self._conflict_engine = ConflictEngine(self)
        return self._conflict_engine

    @property
    def reference(self) -> ReferenceEngine:
        if self._reference_engine is None:
            self._reference_engine = ReferenceEngine(self)
        return self._reference_engine

    @property
    def reflection(self) -> ReflectionEngine:
        if self._reflection_engine is None:
            self._reflection_engine = ReflectionEngine(self)
        return self._reflection_engine

    @property
    def planning(self) -> PlanningEngine:
        if self._planning_engine is None:
            self._planning_engine = PlanningEngine(self)
        return self._planning_engine

    @property
    def agent(self) -> AgentManager:
        if self._agent_manager is None:
            self._agent_manager = AgentManager(self)
        return self._agent_manager

    @property
    def confidence(self) -> ConfidenceEngine:
        if self._confidence_engine is None:
            self._confidence_engine = ConfidenceEngine()
        return self._confidence_engine

    @property
    def network(self) -> AdaptiveCognitiveNetwork:
        if self._adaptive_network is None:
            self._adaptive_network = AdaptiveCognitiveNetwork()
        return self._adaptive_network

    @property
    def obsidian(self) -> SyncManager:
        if self._obsidian_sync is None:
            from mid_brain.obsidian.sync_manager import SyncManager
            vault_path = self.config.obsidian_vault_path or "mid_brain_vault"
            self._obsidian_sync = SyncManager(vault_path, self)
            self._obsidian_sync.initialize()
        return self._obsidian_sync

    @property
    def feedback(self) -> FeedbackBus:
        if self._feedback_bus is None:
            self._feedback_bus = get_feedback_bus()
        return self._feedback_bus

    # ------------------------------------------------------------------ lifecycle

    def initialize(self) -> None:
        """Initialize all Mid Brain components."""
        if self._initialized:
            return

        try:
            # Initialize memory first (foundation for other components)
            self.memory.initialize()
            self._status.components["memory"] = True

            # Initialize knowledge manager
            self.knowledge.initialize()
            self._status.components["knowledge"] = True

            # Initialize reasoning engine
            self.reasoning.initialize()
            self._status.components["reasoning"] = True

            # Initialize conflict engine
            if self.config.enable_conflict_detection:
                self.conflict.initialize()
                self._status.components["conflict"] = True

            # Initialize reference engine
            if self.config.enable_reference:
                self.reference.initialize()
                self._status.components["reference"] = True

            # Initialize reflection engine
            if self.config.enable_reflection:
                self.reflection.initialize()
                self._status.components["reflection"] = True

            # Initialize learning engine
            if self.config.enable_learning:
                self.learning.initialize()
                self._status.components["learning"] = True

            # Initialize planning engine
            if self.config.enable_planning:
                self.planning.initialize()
                self._status.components["planning"] = True

            # Initialize agent manager
            if self.config.enable_agent:
                _ = self.agent.validator  # Trigger initialization
                self._status.components["agent"] = True

            # Initialize confidence engine
            if self.config.enable_confidence:
                _ = self.confidence  # Trigger initialization
                self._status.components["confidence"] = True

            # Initialize adaptive network
            if self.config.enable_network:
                _ = self.network  # Trigger initialization
                self._status.components["network"] = True

            # Initialize Obsidian sync
            if self.config.enable_obsidian and self.config.obsidian_vault_path:
                _ = self.obsidian  # Trigger initialization
                self._status.components["obsidian"] = True

            # Initialize orchestrator (coordinates all components)
            self.orchestrator.initialize()
            self._status.components["orchestrator"] = True

            self._initialized = True
            self._status.initialized = True
            self._status.last_error = None

        except Exception as e:
            self._status.last_error = str(e)
            self._status.initialized = False
            raise

    def health(self) -> dict[str, Any]:
        """Health check endpoint."""
        self._status.uptime_seconds = time.time() - self._start_time
        return {
            "status": "healthy" if self._initialized else "initializing",
            "uptime_seconds": round(self._status.uptime_seconds, 2),
            "components": self._status.components,
            "last_error": self._status.last_error,
            "version": __version__,
        }

    def status(self) -> MidBrainStatus:
        """Get detailed status."""
        self._status.uptime_seconds = time.time() - self._start_time
        return self._status

    def shutdown(self) -> None:
        """Graceful shutdown."""
        self._initialized = False
        self._status.initialized = False

        # Shutdown adapters
        if self._first_brain_adapter:
            self._first_brain_adapter.shutdown()
        if self._second_brain_adapter:
            self._second_brain_adapter.shutdown()

        # Shutdown adaptive network
        if self._adaptive_network:
            self._adaptive_network.close()

    # ------------------------------------------------------------------ main cognitive loop

    def process_question(
        self,
        question: str,
        project_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Main cognitive processing loop (Phase 5+).

        Flow:
        1. Retrieve existing knowledge from Mid Brain
        2. Query First Brain (experience)
        3. Query Second Brain (knowledge)
        4. Compare answers
        5. Detect conflicts
        6. Evaluate evidence
        7. Synthesize answer
        8. Calculate confidence
        9. Make decision
        10. Reflect and learn
        11. Store in memory
        12. Update future reference
        """
        if not self._initialized:
            self.initialize()

        trace_id = str(uuid4())
        return self.orchestrator.process(
            question=question,
            project_id=project_id,
            context=context or {},
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------ explicit knowledge storage

    def store_knowledge(
        self,
        content: str,
        *,
        kind: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        source: str = "mid-brain",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly store knowledge (decision/lesson/fact)."""
        return self.knowledge.create_knowledge(
            content=content,
            kind=kind,
            importance=importance,
            confidence=confidence,
            source=source,
            project_id=project_id,
        )

    # ------------------------------------------------------------------ planning & execution

    def create_plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
    ):
        """Create an execution plan for a goal."""
        return self.planning.create_plan(goal, context, constraints)

    def execute_plan(self, plan) -> list:
        """Execute a plan via the agent manager."""
        return self.agent.execute_plan(plan)

    def create_and_execute(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> tuple:
        """Create a plan and execute it."""
        return self.agent.create_and_execute(goal, context)

    # ------------------------------------------------------------------ obsidian sync

    def sync_to_obsidian(
        self,
        cognitive_output: dict[str, Any],
        phase: str,
        project_id: str | None = None,
        trace_id: str | None = None,
    ):
        """Sync cognitive output to Obsidian vault."""
        if not self.config.enable_obsidian:
            return {"success": False, "error": "Obsidian sync not enabled"}

        from mid_brain.obsidian.note_generator import NoteContext

        note_context = NoteContext(
            trace_id=trace_id or str(uuid4()),
            project_id=project_id,
            cognitive_phase=phase,
        )

        return self.obsidian.sync_to_obsidian(cognitive_output, note_context)

    def sync_from_obsidian(self, since: float | None = None):
        """Sync human edits from Obsidian back to Mid Brain."""
        if not self.config.enable_obsidian:
            return {"success": False, "error": "Obsidian sync not enabled"}

        return self.obsidian.sync_from_obsidian(since=since)

    def full_obsidian_sync(self):
        """Perform full bidirectional Obsidian sync."""
        if not self.config.enable_obsidian:
            return {"success": False, "error": "Obsidian sync not enabled"}

        return self.obsidian.full_sync()
