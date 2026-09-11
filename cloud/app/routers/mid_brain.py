"""Mid Brain API routes - Intelligence Layer (Phase 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.errors import ForbiddenError, NotFoundError
from cloud.app.identity import (
    check_project_id,
    is_foreign_personal,
    project_name_allowed,
    tool_allowed,
)
from cloud.app.security import require_api_key as verify_api_key
from cloud.app.security import require_identity

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/mid-brain", tags=["Mid Brain"])

# Task-level tools that count as code execution (need 'code.execute' grant).
_CODE_TASK_TOOLS = frozenset(
    {"file_write", "code_edit", "terminal", "terminal_run", "file_delete", "code.execute"}
)
# Knowledge kinds that promote shared truth (need 'knowledge.promote' for congty_chung).
_PROMOTE_KINDS = frozenset({"decision", "lesson", "strategy"})


def _deny(tool: str, identity: Identity | None) -> None:
    if not tool_allowed(identity, tool):
        actor = identity.user if identity else "open"
        raise ForbiddenError(f"Tool '{tool}' not granted to '{actor}'")


def _deny_project_scope(identity: Identity | None, project_id: str | None) -> None:
    """Closed mode: non-BGD must scope every cognitive turn to an allowed project."""
    if identity is None:
        return
    if not project_id:
        if not identity.is_bgd:
            raise ForbiddenError("project_id is required (unscoped access is BGD-only)")
        return
    if check_project_id(identity, project_id, get_repository()) is None:
        raise ForbiddenError("Project not in your allowed scope")

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
    identity: Identity | None = Depends(require_identity),
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
    _deny("midbrain.process", identity)
    _deny_project_scope(identity, request.project_id)
    brain = get_mid_brain()

    try:
        context = dict(request.context or {})
        if identity is not None:
            context.setdefault("_actor", identity.user)
            context.setdefault("_phong", identity.phong)
        result = brain.process_question(
            question=request.question,
            project_id=request.project_id,
            context=context,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.post("/knowledge", response_model=StoreKnowledgeResponse)
async def store_knowledge(
    request: StoreKnowledgeRequest,
    identity: Identity | None = Depends(require_identity),
):
    """
    Explicitly store knowledge (decision/lesson/fact).

    This bypasses the cognitive loop and directly stores knowledge
    with the specified metadata. Promoting decision/lesson/strategy to
    congty_chung requires the 'knowledge.promote' grant (truong_phong+BGD).
    """
    _deny("memory.write", identity)
    _deny_project_scope(identity, request.project_id)
    target = None
    if identity is not None and request.project_id:
        target = check_project_id(identity, request.project_id, get_repository())
        if is_foreign_personal(identity, target):
            raise ForbiddenError("Cannot write into another person's personal project")
    if identity is not None and (request.kind or "").lower() in _PROMOTE_KINDS:
        if target == "congty_chung" and not tool_allowed(identity, "knowledge.promote"):
            raise ForbiddenError("Promoting shared knowledge needs 'knowledge.promote'")
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


class CreatePlanRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=5000, description="Goal to plan for")
    project_id: str | None = Field(None, description="Project scope for the plan")
    context: dict = Field(default_factory=dict, description="Additional context")
    constraints: list[str] = Field(default_factory=list, description="Hard constraints")


class ExecutePlanRequest(BaseModel):
    plan_id: str = Field(..., description="Plan created via POST /plan")
    approved_task_ids: list[str] = Field(
        default_factory=list,
        description="Human-approved high-risk task ids (hỏi trước khi chạy)",
    )


@router.post("/plan")
async def create_plan(
    request: CreatePlanRequest,
    identity: Identity | None = Depends(require_identity),
):
    """Decompose a goal into an executable plan (no side effects)."""
    _deny("midbrain.plan", identity)
    _deny_project_scope(identity, request.project_id)
    brain = get_mid_brain()
    context = dict(request.context or {})
    if request.project_id:
        context.setdefault("project_id", request.project_id)
    if identity is not None:
        context.setdefault("_actor", identity.user)
        context.setdefault("_phong", identity.phong)
    try:
        plan = brain.create_plan(
            goal=request.goal, context=context, constraints=request.constraints
        )
        return plan.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")


@router.post("/execute")
async def execute_plan(
    request: ExecutePlanRequest,
    identity: Identity | None = Depends(require_identity),
):
    """Execute a plan. High-risk tasks in approved_task_ids only (no auto-run)."""
    _deny("plan.execute", identity)
    brain = get_mid_brain()
    plan = brain.planning.get_plan(request.plan_id)
    if plan is None:
        raise NotFoundError(f"Plan {request.plan_id} not found")
    if identity is not None and not identity.is_bgd:
        # A plan created in another phong's scope cannot be executed here.
        plan_ctx = (getattr(plan, "metadata", None) or {}).get("context") or {}
        plan_project = plan_ctx.get("project_id")
        if plan_project:
            _deny_project_scope(identity, str(plan_project))
        elif not identity.is_bgd:
            raise ForbiddenError("Unscoped plans are BGD-only")
        for task in plan.tasks:
            task_tools = set(task.tools_allowed or [])
            if task_tools & _CODE_TASK_TOOLS and not tool_allowed(identity, "code.execute"):
                raise ForbiddenError(
                    f"Task {task.task_id} needs 'code.execute' (not granted to '{identity.user}')"
                )
    try:
        results = brain.execute_plan(plan, approved_ids=set(request.approved_task_ids or []))
        return {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "results": [
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "output": (r.output or "")[:2000],
                    "error": r.error,
                    "files_changed": r.files_changed,
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ],
        }
    except ForbiddenError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.get("/approvals/pending")
async def pending_approvals(
    identity: Identity | None = Depends(require_identity),
):
    """List high-risk tasks waiting for human approval (hỏi trước khi chạy)."""
    _deny("plan.execute", identity)
    brain = get_mid_brain()
    return {"pending": brain.agent.approval.get_pending()}


class ApprovalDecision(BaseModel):
    approve: bool = Field(..., description="True=approve, False=reject")
    reason: str = Field("", description="Rejection reason when approve=false")


@router.post("/approvals/{approval_id}")
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    identity: Identity | None = Depends(require_identity),
):
    """Human approves/rejects a pending high-risk task."""
    _deny("plan.execute", identity)
    brain = get_mid_brain()
    actor = identity.user if identity else "human"
    if decision.approve:
        ok = brain.agent.approval.approve(approval_id, approved_by=actor)
    else:
        ok = brain.agent.approval.reject(
            approval_id, reason=decision.reason or "rejected", rejected_by=actor
        )
    if not ok:
        raise NotFoundError(f"Approval {approval_id} not found")
    return {"approval_id": approval_id, "approved": decision.approve, "by": actor}


@router.get("/trace/{trace_id}")
async def get_trace(
    trace_id: str,
    days: int = Query(7, ge=1, le=30, description="How many daily trace files to scan"),
    identity: Identity | None = Depends(require_identity),
):
    """Fetch cognitive-turn trace events by trace_id (debuggability per assistant)."""
    _deny("midbrain.process", identity)
    import json as _json
    from datetime import date as _date
    from datetime import timedelta as _timedelta
    from pathlib import Path as _Path

    brain = get_mid_brain()
    trace_dir = getattr(brain.config, "trace_dir", "") or "mid_brain_data/traces"
    base = _Path(trace_dir)
    events: list[dict] = []
    for back in range(days):
        day = (_date.today() - _timedelta(days=back)).strftime("%Y-%m-%d")
        fp = base / f"{day}.jsonl"
        if not fp.is_file():
            continue
        try:
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or trace_id not in line:
                    continue
                try:
                    rec = _json.loads(line)
                except ValueError:
                    continue
                if rec.get("trace_id") == trace_id:
                    events.append(rec)
                    if len(events) >= 200:
                        break
        except OSError:
            continue
        if len(events) >= 200:
            break
    if not events:
        raise NotFoundError(f"Trace {trace_id} not found")
    return {"trace_id": trace_id, "events": events}


@router.get("/memory/stats")
async def memory_stats(
    project_id: str | None = Query(None, description="Filter by project"),
    identity: Identity | None = Depends(require_identity),
):
    """Get Mid Brain memory statistics."""
    _deny_project_scope(identity, project_id)
    brain = get_mid_brain()
    stats = brain.memory.get_stats()
    if project_id:
        stats["project_id"] = project_id
    return stats


@router.get("/knowledge/stats")
async def knowledge_stats(
    project_id: str | None = Query(None, description="Filter by project"),
    identity: Identity | None = Depends(require_identity),
):
    """Get Mid Brain knowledge statistics (counts only, never content)."""
    _deny_project_scope(identity, project_id)
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
    identity: Identity | None = Depends(require_identity),
):
    """Get Mid Brain learning statistics (counts only, never content)."""
    _deny_project_scope(identity, project_id)
    brain = get_mid_brain()
    try:
        # LearningEngine: get_lessons / get_decisions / search_learning
        lessons = brain.learning.get_lessons(project_id=project_id) if hasattr(brain.learning, "get_lessons") else []
        decisions = brain.learning.get_decisions(project_id=project_id) if hasattr(brain.learning, "get_decisions") else []
        return {"lessons": len(lessons) if isinstance(lessons, list) else 0, "decisions": len(decisions) if isinstance(decisions, list) else 0, "project_id": project_id}
    except Exception:
        return {"lessons": 0, "decisions": 0, "project_id": project_id}