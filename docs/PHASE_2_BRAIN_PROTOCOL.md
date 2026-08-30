# Phase 2: Three Brain Communication Protocol — Implementation Complete

## Overview

Phase 2 implements the communication protocol between the three brains:
- **First Brain** (Experience) — Local agent with episodic memory, perception
- **Mid Brain** (Intelligence) — Cognitive orchestration, reasoning, conflict resolution, learning
- **Second Brain** (Knowledge) — Cloud API with semantic memory, RAG, projects

## Architecture

```
┌─────────────────┐     HTTP/JSON      ┌─────────────────┐     HTTP/JSON      ┌─────────────────┐
│  First Brain    │ ◄─────────────────► │   Mid Brain     │ ◄─────────────────► │  Second Brain   │
│  (Experience)   │   Brain Protocol    │  (Intelligence) │   Brain Protocol    │  (Knowledge)    │
└─────────────────┘                     └─────────────────┘                     └─────────────────┘
```

## Components Implemented

### 1. Brain Protocol (`mid_brain/api/brain_protocol.py`)

Defines the message schema for inter-brain communication:

**Message Types (15):**
- `QUESTION` — Ask a brain for an answer
- `ANSWER` — Response with answer and confidence
- `REQUEST_EVIDENCE` — Ask for supporting evidence
- `CHALLENGE` — Challenge another brain's answer
- `VERIFY` — Request verification of a claim
- `COMPARE` — Request comparison of two answers
- `SYNTHESIZE` — Request synthesis of multiple answers
- `LEARN` — Share learning for storage
- `REFLECT` — Share reflection
- `RECALL` — Request memory recall
- `CONFLICT` — Report detected conflict
- `PROMOTE` — Promote knowledge status
- `REJECT` — Reject knowledge
- `HEALTH_CHECK` — Health probe
- `STATUS` — Status update

**Schemas:**
- `BrainMessage` — Core message with trace_id, timestamp, TTL
- `BrainRequest` — Request wrapper with context
- `BrainResponse` — Response with success/error
- `BrainEvent` — Event notification

### 2. First Brain Adapter (`mid_brain/api/first_brain_adapter.py`)

HTTP adapter connecting Mid Brain to First Brain (local agent):

```python
adapter = FirstBrainAdapter(base_url="http://127.0.0.1:8100", api_key="dev-local-key")
adapter.initialize()

# Ask a question
response = adapter.ask(
    question="What is Python?",
    project_id="proj-1",
    trace_id="trace-123",
    context={"source": "mid-brain"}
)

# Search memories
response = adapter.search_memory(
    query="Python",
    project_id="proj-1",
    top_k=10
)

# Store memory
response = adapter.store_memory(
    content="Python is a programming language",
    question="What is Python?",
    project_id="proj-1",
    trace_id="trace-123"
)
```

**Methods:**
- `ask()` — Question First Brain agent
- `search_memory()` — Search episodic/semantic memory
- `store_memory()` — Store new memory
- `health_check()` — Probe First Brain health
- `get_status()` — Get status

### 3. Second Brain Adapter (`mid_brain/api/second_brain_adapter.py`)

HTTP adapter connecting Mid Brain to Second Brain (cloud API):

```python
adapter = SecondBrainAdapter(base_url="http://127.0.0.1:8100", api_key="dev-local-key")
adapter.initialize()

# Search memories
response = adapter.search_memory(
    query="Python",
    project_id="proj-1",
    top_k=8
)

# Store memory
response = adapter.store_memory(
    content="Python is a programming language",
    question="What is Python?",
    project_id="proj-1",
    trace_id="trace-123"
)

# Verify claim
response = adapter.verify_claim(
    claim="Python was created in 1991",
    project_id="proj-1"
)

# Get conflicts
response = adapter.get_conflicts(project_id="proj-1")

# Learn (store decision/lesson)
response = adapter.learn(
    learning_type="decision",
    content="Use Python for data processing",
    confidence=0.9,
    project_id="proj-1"
)

# Get projects
response = adapter.get_projects()
```

**Methods:**
- `search_memory()` — Semantic search via Second Brain
- `store_memory()` — Store in Second Brain
- `verify_claim()` — Verify against knowledge base
- `get_conflicts()` — Get detected conflicts
- `learn()` — Store learning (decision/lesson/strategy/failure/success)
- `get_projects()` — List projects
- `health_check()` — Probe Second Brain health
- `get_status()` — Get status

### 4. Mock Adapters (`mid_brain/api/mock_adapters.py`)

Testing implementations for unit tests without running servers:

```python
from mid_brain.api.mock_adapters import MockFirstBrainAdapter, MockSecondBrainAdapter

mock_first = MockFirstBrainAdapter()
mock_second = MockSecondBrainAdapter()

# Configure mock responses
mock_first.set_ask_response("Mock answer", 0.8)
mock_second.set_search_response([{"content": "Mock memory", "score": 0.9}])

# Use in tests
mid_brain = MidBrain(config)
mid_brain._first_brain_adapter = mock_first
mid_brain._second_brain_adapter = mock_second
```

## Integration with Cognitive Orchestrator

The `CognitiveOrchestrator` now uses real adapters in the cognitive loop (Step 3: QUESTION):

```python
# In cognitive_orchestrator.py
def _query_first_brain(self, question, project_id, context):
    try:
        response = self.mid_brain.first_brain.ask(
            question=question,
            project_id=project_id,
            trace_id=context.get("trace_id"),
            context=context,
        )
        if response.success and response.message:
            return response.message.payload.get("answer")
    except Exception:
        pass
    return None

def _query_second_brain(self, question, project_id, context):
    try:
        response = self.mid_brain.second_brain.search(
            query=question,
            project_id=project_id,
            top_k=8,
        )
        if response.success and response.message:
            return response.message.payload.get("answer")
    except Exception:
        pass
    return None
```

The adapters are lazy-initialized via properties in `MidBrain`:

```python
@property
def first_brain(self) -> "FirstBrainAdapter":
    if self._first_brain_adapter is None:
        from mid_brain.api.first_brain_adapter import FirstBrainAdapter
        self._first_brain_adapter = FirstBrainAdapter(
            base_url=self.config.first_brain_url,
            api_key=self.config.first_brain_api_key,
        )
        self._first_brain_adapter.initialize()
    return self._first_brain_adapter
```

## Mid Brain API Routes (`cloud/app/routers/mid_brain.py`)

Exposes Mid Brain functionality via REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/mid-brain/health` | GET | Health check |
| `/v1/mid-brain/status` | GET | Detailed status |
| `/v1/mid-brain/process` | POST | Execute cognitive loop |
| `/v1/mid-brain/knowledge` | POST | Explicit knowledge storage |
| `/v1/mid-brain/memory/stats` | GET | Memory statistics |
| `/v1/mid-brain/knowledge/stats` | GET | Knowledge statistics |
| `/v1/mid-brain/learning/stats` | GET | Learning statistics |

**Process Request:**
```json
{
  "question": "What is the best approach for this problem?",
  "project_id": "proj-1",
  "context": {"priority": "high"}
}
```

**Process Response:**
```json
{
  "question": "What is the best approach...",
  "answer": "Based on analysis...",
  "confidence": 0.85,
  "trace_id": "abc123",
  "total_duration_ms": 1250,
  "steps": [
    {"phase": "RECALL", "input": {...}, "output": {...}, "duration_ms": 45, "success": true},
    {"phase": "UNDERSTAND", ...},
    {"phase": "QUESTION", "output": {"first_brain": true, "second_brain": true}, ...},
    {"phase": "COMPARE", ...},
    {"phase": "CONFLICT_DETECTION", "output": {"conflicts_count": 0}, ...},
    {"phase": "EVIDENCE", ...},
    {"phase": "CONFIDENCE", "output": {"confidence": 0.85}, ...},
    {"phase": "SYNTHESIS", "output": {"answer_length": 234}, ...},
    {"phase": "DECISION", "output": {"should_store": true}, ...},
    {"phase": "REFLECTION", "output": {"stored": true}, ...},
    {"phase": "LEARNING", "output": {"stored_count": 2}, ...},
    {"phase": "MEMORY", "output": {"stored": true}, ...},
    {"phase": "FUTURE_REFERENCE", "output": {"indexed": true}, ...}
  ],
  "memories_used": 3,
  "knowledge_used": 0,
  "conflicts_detected": 0,
  "learning_stored": 2,
  "reflection_stored": 1,
  "sources": {
    "first_brain": "Answer from experience...",
    "second_brain": "Answer from knowledge...",
    "mid_brain_memory": {"results": [...]}
  }
}
```

## Configuration

Added to `cloud/app/config.py` and `cloud/.env`:

```python
# Mid Brain Configuration
mid_brain_first_brain_url: str = "http://127.0.0.1:8100"
mid_brain_second_brain_url: str = "http://127.0.0.1:8100"
mid_brain_enable_reflection: bool = True
mid_brain_enable_learning: bool = True
mid_brain_enable_conflict_detection: bool = True
mid_brain_enable_reference: bool = True
mid_brain_confidence_threshold: float = 0.5
```

## Testing

All tests pass:

```
# Cloud + Local tests
192 passed, 4 skipped (PG integration auto-skips without Docker)

# Mid Brain tests
23 passed
```

### Mid Brain Test Coverage

- **Core**: Initialization, health, status
- **Memory**: Store/retrieve/search/link across 6 types
- **Knowledge**: Lifecycle (candidate→validated→trusted→master), deprecation, versioning
- **Reasoning**: Compare, confidence calculation, evidence evaluation
- **Conflict**: Negation detection, numerical discrepancy, empty handling
- **Reference**: Indexing, similar experience retrieval
- **Reflection**: 9-prompt structured reflection
- **Learning**: Extraction (experience/decision/lesson/strategy/failure/success)
- **Integration**: Full 14-step cognitive loop, explicit knowledge storage

## Usage Example

```python
from mid_brain.core.mid_brain import MidBrain, MidBrainConfig

# Configure
config = MidBrainConfig(
    first_brain_url="http://127.0.0.1:8100",
    second_brain_url="http://127.0.0.1:8100",
    enable_reflection=True,
    enable_learning=True,
    enable_conflict_detection=True,
    enable_reference=True,
    confidence_threshold=0.5,
)

# Create and initialize
brain = MidBrain(config)
brain.initialize()

# Process a question through the full cognitive loop
result = brain.process_question(
    question="What is the best database for this use case?",
    project_id="proj-1",
    context={"priority": "high"}
)

print(f"Answer: {result['answer']}")
print(f"Confidence: {result['confidence']}")
print(f"Steps: {len(result['steps'])}")
print(f"Conflicts: {result['conflicts_detected']}")
print(f"Learning stored: {result['learning_stored']}")

# Explicitly store knowledge
brain.store_knowledge(
    content="Decision: Use PostgreSQL for production",
    kind="decision",
    importance=0.9,
    confidence=0.95,
    source="architect",
    project_id="proj-1"
)

# Health check
print(brain.health())
# {'status': 'healthy', 'uptime_seconds': 45.2, 'components': {...}, 'version': '1.0.0'}

# Shutdown
brain.shutdown()
```

## Next Steps (Phase 3+)

- **Phase 3**: Advanced reasoning (causal, counterfactual, analogical)
- **Phase 4**: Meta-cognition (strategy selection, resource allocation)
- **Phase 5**: Persistent knowledge graph with embeddings
- **Phase 6**: Cross-brain learning propagation
- **Phase 7**: Human-in-the-loop interfaces
- **Phase 8**: Obsidian integration for Mid Brain (draft notes, human review)
- **Phase 9**: Distributed deployment
- **Phase 10**: Production hardening
- **Phase 11**: Observability & monitoring
- **Phase 12**: Documentation & examples

## Files Created/Modified

### New Files
- `mid_brain/api/brain_protocol.py` — Protocol schemas
- `mid_brain/api/first_brain_adapter.py` — First Brain HTTP adapter
- `mid_brain/api/second_brain_adapter.py` — Second Brain HTTP adapter
- `mid_brain/api/mock_adapters.py` — Mock adapters for testing
- `cloud/app/routers/mid_brain.py` — Mid Brain REST API routes

### Modified Files
- `mid_brain/core/mid_brain.py` — Added adapter properties, integrated into initialize/shutdown
- `mid_brain/core/cognitive_orchestrator.py` — Real adapter calls in QUESTION step
- `cloud/app/config.py` — Added Mid Brain settings
- `cloud/app/main.py` — Registered mid_brain router
- `cloud/.env` — Added Mid Brain environment variables
- `cloud/.env.example` — Added Mid Brain template
- `docs/PHASE_2_BRAIN_PROTOCOL.md` — This documentation