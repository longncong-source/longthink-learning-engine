# PHASE 1 — MID BRAIN SKELETON

## Mục tiêu

Tạo bộ khung Mid Brain như một module độc lập, chưa implement adaptive learning, neural network, hay complex reasoning.

## Kết quả đạt được

✅ Tạo cấu trúc thư mục Mid Brain:
```
mid_brain/
├── core/
│   ├── __init__.py
│   ├── mid_brain.py              # MidBrain class chính
│   └── cognitive_orchestrator.py # CognitiveOrchestrator
├── memory/
│   ├── __init__.py
│   └── memory_manager.py         # MemoryManager
├── knowledge/
│   ├── __init__.py
│   └── knowledge_manager.py      # KnowledgeManager
├── reasoning/
│   ├── __init__.py
│   └── reasoning_engine.py       # ReasoningEngine
├── learning/
│   ├── __init__.py
│   └── learning_engine.py        # LearningEngine
├── conflict/
│   ├── __init__.py
│   └── conflict_engine.py        # ConflictEngine
├── reference/
│   ├── __init__.py
│   └── reference_engine.py       # ReferenceEngine
├── reflection/
│   ├── __init__.py
│   └── reflection_engine.py      # ReflectionEngine
├── api/
├── tests/
│   ├── __init__.py
│   └── test_mid_brain.py         # 23 tests
```

## Các Interface/Class đã implement

### 1. MidBrain (mid_brain/core/mid_brain.py)
```python
class MidBrain:
    def __init__(self, config: MidBrainConfig | None = None) -> None
    def initialize(self) -> None
    def health(self) -> dict[str, Any]
    def status(self) -> MidBrainStatus
    def shutdown(self) -> None
    def process_question(self, question: str, project_id: str | None = None, context: dict | None = None) -> dict
    def store_knowledge(self, content: str, kind: str | None = None, importance: float | None = None, confidence: float | None = None, source: str = "mid-brain", project_id: str | None = None) -> dict
```

### 2. CognitiveOrchestrator (mid_brain/core/cognitive_orchestrator.py)
```python
class CognitiveOrchestrator:
    def __init__(self, mid_brain: MidBrain) -> None
    def initialize(self) -> None
    def process(self, question: str, project_id: str | None, context: dict, trace_id: str) -> dict
```

### 3. MemoryManager (mid_brain/memory/memory_manager.py)
```python
class MemoryManager:
    def __init__(self, db_path: str = "mid_brain_data/memory.db") -> None
    def initialize(self) -> None
    def store(self, content: str, question: str | None = None, memory_type: str = "semantic", project_id: str | None = None, confidence: float = 0.5, importance: float = 0.5, source: str = "mid-brain", trace_id: str | None = None, metadata: dict | None = None) -> dict
    def retrieve(self, query: MemoryQuery | str, **kwargs) -> dict
    def get(self, memory_id: str) -> MemoryItem | None
    def update(self, memory_id: str, fields: dict) -> MemoryItem | None
    def delete(self, memory_id: str) -> bool
    def link(self, source_id: str, target_id: str, link_type: str, weight: float = 1.0) -> bool
    def get_links(self, memory_id: str) -> list[dict]
    def promote(self, memory_id: str, new_type: str) -> MemoryItem | None
    def archive(self, memory_id: str) -> bool
    def get_stats(self) -> dict
```

**Memory Types:** working, episodic, semantic, procedural, strategic, meta

### 4. KnowledgeManager (mid_brain/knowledge/knowledge_manager.py)
```python
class KnowledgeManager:
    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/knowledge.db") -> None
    def initialize(self) -> None
    def create_knowledge(self, content: str, kind: str | None = None, importance: float | None = None, confidence: float | None = None, source: str = "mid-brain", project_id: str | None = None, evidence: list[str] | None = None) -> dict
    def validate_knowledge(self, knowledge_id: str, validated_by: str = "mid-brain", evidence: list[str] | None = None, confidence: float | None = None) -> dict
    def promote_knowledge(self, knowledge_id: str, new_status: str, promoted_by: str = "mid-brain", evidence: list[str] | None = None, confidence: float | None = None) -> dict
    def deprecate_knowledge(self, knowledge_id: str, deprecated_by: str = "mid-brain", reason: str = "") -> dict
    def reject_knowledge(self, knowledge_id: str, rejected_by: str = "mid-brain", reason: str = "") -> dict
    def update_knowledge(self, knowledge_id: str, content: str | None = None, confidence: float | None = None, importance: float | None = None, evidence: list[str] | None = None, updated_by: str = "mid-brain", reason: str = "Updated") -> dict
    def get_knowledge_history(self, knowledge_id: str) -> list[dict]
    def get(self, knowledge_id: str) -> KnowledgeItem | None
    def search(self, query: str, project_id: str | None = None, status: str | None = None, knowledge_type: str | None = None, min_confidence: float = 0.0, limit: int = 10) -> dict
    def get_trusted_knowledge(self, query: str, project_id: str | None = None, limit: int = 5) -> list[dict]
```

**Knowledge Types:** fact, inference, hypothesis, opinion, unknown

**Knowledge Statuses:** candidate → validated → trusted → master (also deprecated, rejected)

### 5. ReasoningEngine (mid_brain/reasoning/reasoning_engine.py)
```python
class ReasoningEngine:
    def __init__(self, mid_brain: MidBrain) -> None
    def initialize(self) -> None
    def compare_answers(self, first_brain_answer: str | None, second_brain_answer: str | None, question: str) -> dict
    def evaluate_evidence(self, first_brain_answer: str | None, second_brain_answer: str | None, recall_result: dict, conflicts: list[dict]) -> dict
    def calculate_confidence(self, evidence: dict, conflicts: list[dict], first_brain_answer: str | None, second_brain_answer: str | None) -> float
    def explain_confidence(self, evidence: dict, conflicts: list[dict], first_brain_answer: str | None, second_brain_answer: str | None, confidence: float) -> str
    def synthesize(self, question: str, first_brain_answer: str | None, second_brain_answer: str | None, comparison: dict, evidence: dict, confidence: float) -> dict
```

### 6. ConflictEngine (mid_brain/conflict/conflict_engine.py)
```python
class ConflictEngine:
    def __init__(self, mid_brain: MidBrain) -> None
    def initialize(self) -> None
    def detect(self, first_brain_answer: str | None, second_brain_answer: str | None, question: str) -> list[dict]
    def investigate(self, conflict_id: str, evidence_a: list[str], evidence_b: list[str]) -> dict
    def resolve(self, conflict_id: str, resolution: str, confidence: float, resolved_by: str = "mid-brain") -> dict
    def accept_uncertain(self, conflict_id: str, reason: str) -> dict
    def get_conflict(self, conflict_id: str) -> ConflictObject | None
    def list_conflicts(self, status: ConflictStatus | None = None) -> list[dict]
    def get_open_conflicts(self) -> list[dict]
```

**Conflict Statuses:** open → investigating → resolved / unresolved / accepted_as_uncertain

**Conflict Severity:** low, medium, high, critical

### 7. ReferenceEngine (mid_brain/reference/reference_engine.py)
```python
class ReferenceEngine:
    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/reference.db") -> None
    def initialize(self) -> None
    def index(self, question: str, answer: str, confidence: float, trace_id: str, project_id: str | None = None, tags: list[str] | None = None, success: bool = True, metadata: dict | None = None) -> dict
    def retrieve(self, query: ReferenceQuery | str, **kwargs) -> dict
    def find_similar_experience(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict]
    def find_similar_decision(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict]
    def find_relevant_lesson(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict]
    def find_relevant_strategy(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict]
    def find_previous_failure(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict]
```

### 8. ReflectionEngine (mid_brain/reflection/reflection_engine.py)
```python
class ReflectionEngine:
    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/reflection.db") -> None
    def initialize(self) -> None
    def reflect(self, question: str, answer: str, confidence: float, steps: list[dict], project_id: str | None = None, trace_id: str | None = None) -> dict
    def get_reflection(self, reflection_id: str) -> dict | None
    def get_reflections_for_question(self, question: str, limit: int = 5) -> list[dict]
    def get_recent_reflections(self, limit: int = 10) -> list[dict]
```

**Reflection Prompts (9 questions):**
1. What did we know?
2. What did we assume?
3. What evidence was used?
4. What was correct?
5. What was wrong?
6. What changed our conclusion?
7. What should be remembered?
8. What should be deprecated?
9. What should improve next time?

### 9. LearningEngine (mid_brain/learning/learning_engine.py)
```python
class LearningEngine:
    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/learning.db") -> None
    def initialize(self) -> None
    def extract_learning(self, question: str, answer: str, confidence: float, project_id: str | None = None, trace_id: str | None = None) -> dict
    def get_learning(self, learning_id: str) -> LearningItem | None
    def search_learning(self, query: str, learning_type: str | None = None, project_id: str | None = None, min_confidence: float = 0.0, limit: int = 10) -> list[dict]
    def get_lessons(self, project_id: str | None = None, limit: int = 10) -> list[dict]
    def get_decisions(self, project_id: str | None = None, limit: int = 10) -> list[dict]
    def get_strategies(self, project_id: str | None = None, limit: int = 10) -> list[dict]
    def get_failures(self, project_id: str | None = None, limit: int = 10) -> list[dict]
```

**Learning Types:** experience, decision, lesson, strategy, failure, success

**Learning Lifecycle:** OBSERVE → ANALYZE → REFLECT → LEARN → STORE → REUSE

## Tests

✅ 23 tests passed:
- TestMidBrainCore (2 tests)
- TestMemoryManager (4 tests)
- TestKnowledgeManager (2 tests)
- TestReasoningEngine (4 tests)
- TestConflictEngine (3 tests)
- TestReferenceEngine (2 tests)
- TestReflectionEngine (2 tests)
- TestLearningEngine (2 tests)
- TestFullCognitiveLoop (2 tests)

## Verification

```bash
# Run Mid Brain tests
.\.venv\Scripts\python.exe -m pytest mid_brain/tests/test_mid_brain.py -v

# Run all tests (original + Mid Brain)
.\.venv\Scripts\python.exe -m pytest -q

# Lint
.\.venv\Scripts\python.exe -m ruff check mid_brain
```

## Kết luận

Phase 1 **PASS** - Mid Brain skeleton hoàn chỉnh với đầy đủ interfaces, tests pass, không phá vỡ First Brain hoặc Second Brain hiện tại.

## Tiếp theo

Phase 2 — Three Brain Communication Protocol