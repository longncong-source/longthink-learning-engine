"""Mid Brain API routes - Intelligence Layer (Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cloud.app.security import require_api_key as verify_api_key
from cloud.app.config import get_settings

router = APIRouter(prefix="/v1/mid-brain", tags=["Mid Brain"])

# Global Mid Brain instance
_mid_brain = None


def get_mid_brain():
    """Get or create Mid Brain instance."""
    global _mid_brain
    if _mid_brain is None:
        from mid_brain.core.mid_brain import MidBrain, MidBrainConfig
        settings = get_settings()
        api_key = settings.api_key_list[0] if settings.api_key_list else "dev-local-key"
        config = MidBrainConfig(
            first_brain_url=settings.mid_brain_first_brain_url,
            first_brain_api_key=api_key,
            second_brain_url=settings.mid_brain_second_brain_url,
            second_brain_api_key=api_key,
            enable_reflection=settings.mid_brain_enable_reflection,
            enable_learning=settings.mid_brain_enable_learning,
            enable_conflict_detection=settings.mid_brain_enable_conflict_detection,
            enable_reference=settings.mid_brain_enable_reference,
            enable_planning=settings.mid_brain_enable_planning,
            enable_agent=settings.mid_brain_enable_agent,
            enable_confidence=settings.mid_brain_enable_confidence,
            enable_network=settings.mid_brain_enable_network,
            enable_obsidian=settings.mid_brain_enable_obsidian,
            obsidian_vault_path=settings.mid_brain_obsidian_vault_path,
            confidence_threshold=settings.mid_brain_confidence_threshold,
        )
        _mid_brain = MidBrain(config)
        _mid_brain.initialize()
    return _mid_brain


# Request/Response Models
class ProcessQuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000, description="Question to process")
    project_id: str | None = Field(None, description="Optional project ID for context")
    context: dict = Field(default_factory=dict, description="Additional context")


class ProcessQuestionResponse(BaseModel):
    question: str
    answer: str
    confidence: float
    trace_id: str
    total_duration_ms: float
    steps: list[dict]
    memories_used: int
    knowledge_used: int
    conflicts_detected: int
    learning_stored: int
    reflection_stored: int
    sources: dict


class StoreKnowledgeRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    kind: str | None = Field(None, description="Knowledge type: fact, decision, lesson, strategy, etc.")
    importance: float | None = Field(None, ge=0.0, le=1.0)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    source: str = Field("mid-brain", description="Source of knowledge")
    project_id: str | None = None


class StoreKnowledgeResponse(BaseModel):
    created: bool
    knowledge_id: str
    status: str
    version: int


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    components: dict[str, bool]
    last_error: str | None
    version: str


class StatusResponse(BaseModel):
    initialized: bool
    uptime_seconds: float
    components: dict[str, bool]
    last_error: str | None


@router.get("/health", response_model=HealthResponse)
async def health(_: str = Depends(verify_api_key)):
    """Mid Brain health check."""
    brain = get_mid_brain()
    return brain.health()


@router.get("/status", response_model=StatusResponse)
async def status(_: str = Depends(verify_api_key)):
    """Mid Brain detailed status."""
    brain = get_mid_brain()
    s = brain.status()
    return {
        "initialized": s.initialized,
        "uptime_seconds": s.uptime_seconds,
        "components": s.components,
        "last_error": s.last_error,
    }


@router.post("/process", response_model=ProcessQuestionResponse)
async def process_question(
    request: ProcessQuestionRequest,
    _: str = Depends(verify_api_key),
):
    """
    Main cognitive processing endpoint.
    
    Executes the full 14-step cognitive loop:
    1. RECALL - Retrieve from Mid Brain memory
    2. UNDERSTAND - Analyze question intent
    3. QUESTION - Query First Brain & Second Brain
    4. COMPARE - Compare answers
    5. CONFLICT_DETECTION - Detect contradictions
    6. EVIDENCE - Evaluate supporting evidence
    7. CONFIDENCE - Calculate confidence score
    8. SYNTHESIS - Synthesize final answer
    9. DECISION - Determine if storage is needed
    10. REFLECTION - Reflect on the process
    11. LEARNING - Extract and store learning
    12. MEMORY - Store in Mid Brain memory
    13. FUTURE_REFERENCE - Index for future retrieval
    """
    brain = get_mid_brain()
    
    try:
        result = brain.process_question(
            question=request.question,
            project_id=request.project_id,
            context=request.context,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/knowledge", response_model=StoreKnowledgeResponse)
async def store_knowledge(
    request: StoreKnowledgeRequest,
    _: str = Depends(verify_api_key),
):
    """
    Explicitly store knowledge (decision/lesson/fact).
    
    This bypasses the cognitive loop and directly stores knowledge
    with the specified metadata.
    """
    brain = get_mid_brain()
    
    try:
        result = brain.store_knowledge(
            content=request.content,
            kind=request.kind,
            importance=request.importance,
            confidence=request.confidence,
            source=request.source,
            project_id=request.project_id,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage failed: {str(e)}")


@router.get("/memory/stats")
async def memory_stats(
    project_id: str | None = Query(None, description="Filter by project"),
    _: str = Depends(verify_api_key),
):
    """Get Mid Brain memory statistics."""
    brain = get_mid_brain()
    stats = brain.memory.get_stats()
    if project_id:
        stats["project_id"] = project_id
    return stats


@router.get("/knowledge/stats")
async def knowledge_stats(
    project_id: str | None = Query(None, description="Filter by project"),
    _: str = Depends(verify_api_key),
):
    """Get Mid Brain knowledge statistics."""
    brain = get_mid_brain()
    # KnowledgeManager has search/get_trusted_knowledge, no get_stats — synthesize
    try:
        trusted = brain.knowledge.get_trusted_knowledge(project_id=project_id, limit=1000)
        all_items = brain.knowledge.search("", project_id=project_id, limit=1000) if hasattr(brain.knowledge, "search") else []
        return {"total": len(all_items), "trusted": len(trusted), "project_id": project_id}
    except Exception:
        return {"total": 0, "trusted": 0, "project_id": project_id}


@router.get("/learning/stats")
async def learning_stats(
    project_id: str | None = Query(None, description="Filter by project"),
    _: str = Depends(verify_api_key),
):
    """Get Mid Brain learning statistics."""
    brain = get_mid_brain()
    try:
        # LearningEngine: get_lessons / get_decisions / search_learning
        lessons = brain.learning.get_lessons(project_id=project_id) if hasattr(brain.learning, "get_lessons") else []
        decisions = brain.learning.get_decisions(project_id=project_id) if hasattr(brain.learning, "get_decisions") else []
        return {"lessons": len(lessons) if isinstance(lessons, list) else 0, "decisions": len(decisions) if isinstance(decisions, list) else 0, "project_id": project_id}
    except Exception:
        return {"lessons": 0, "decisions": 0, "project_id": project_id}