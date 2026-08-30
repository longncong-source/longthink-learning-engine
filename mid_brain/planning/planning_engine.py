"""Planning Engine for Mid Brain - Task planning and decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class TaskSpec:
    """Task specification for agent execution."""

    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    objective: str = ""
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    priority: str = "medium"  # low, medium, high, critical
    risk_level: str = "low"  # low, medium, high
    expected_output: str = ""
    tools_allowed: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    validation_rules: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # task_ids
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "description": self.description,
            "context": self.context,
            "constraints": self.constraints,
            "priority": self.priority,
            "risk_level": self.risk_level,
            "expected_output": self.expected_output,
            "tools_allowed": self.tools_allowed,
            "timeout_seconds": self.timeout_seconds,
            "validation_rules": self.validation_rules,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class Plan:
    """Execution plan consisting of multiple tasks."""

    plan_id: str = field(default_factory=lambda: uuid4().hex[:12])
    goal: str = ""
    tasks: list[TaskSpec] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"  # pending, executing, completed, failed
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "tasks": [t.to_dict() for t in self.tasks],
            "created_at": self.created_at,
            "status": self.status,
            "metadata": self.metadata,
        }


class PlanningEngine:
    """Plans and decomposes goals into executable tasks."""

    def __init__(self, mid_brain: Any = None) -> None:
        self.mid_brain = mid_brain
        self._plans: dict[str, Plan] = {}

    def initialize(self) -> None:
        """Initialize the planning engine."""
        pass

    def create_plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
    ) -> Plan:
        """Create a high-level plan for a goal."""
        plan = Plan(goal=goal, metadata={"context": context or {}, "constraints": constraints or []})

        # Simple decomposition: break goal into steps
        # In production, this would use LLM for intelligent decomposition
        steps = self._decompose_goal(goal, context or {})

        for i, step in enumerate(steps):
            task = TaskSpec(
                objective=step["objective"],
                description=step.get("description", ""),
                context={**(context or {}), "step": i + 1, "total_steps": len(steps)},
                constraints=constraints or [],
                priority=step.get("priority", "medium"),
                risk_level=step.get("risk_level", "low"),
                expected_output=step.get("expected_output", ""),
                tools_allowed=step.get("tools_allowed", []),
                timeout_seconds=step.get("timeout_seconds", 300),
                validation_rules=step.get("validation_rules", []),
                dependencies=step.get("dependencies", []),
            )
            plan.tasks.append(task)

        self._plans[plan.plan_id] = plan
        return plan

    def _decompose_goal(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Decompose goal into steps (simplified implementation)."""
        # This is a simplified heuristic decomposition
        # In production, use LLM or more sophisticated planning

        goal_lower = goal.lower()
        steps = []

        if "research" in goal_lower or "investigate" in goal_lower:
            steps.append({
                "objective": f"Research and gather information about: {goal}",
                "description": "Search internal memory and external sources",
                "priority": "high",
                "risk_level": "low",
                "tools_allowed": ["memory_search", "web_search", "document_search"],
                "expected_output": "Summary of findings with sources",
                "validation_rules": ["At least 3 sources cited", "Confidence > 0.7"],
            })
            steps.append({
                "objective": "Synthesize findings into coherent answer",
                "description": "Combine research into structured response",
                "priority": "high",
                "risk_level": "low",
                "tools_allowed": ["synthesis", "writing"],
                "expected_output": "Final synthesized answer",
                "validation_rules": ["Addresses original question", "Cites sources"],
            })

        elif "implement" in goal_lower or "build" in goal_lower or "create" in goal_lower:
            steps.append({
                "objective": f"Design solution for: {goal}",
                "description": "Create technical design and approach",
                "priority": "high",
                "risk_level": "medium",
                "tools_allowed": ["design", "architecture"],
                "expected_output": "Design document",
                "validation_rules": ["Design is complete", "Dependencies identified"],
            })
            steps.append({
                "objective": "Implement the solution",
                "description": "Write code and create files",
                "priority": "high",
                "risk_level": "medium",
                "tools_allowed": ["file_write", "code_edit", "terminal"],
                "expected_output": "Working implementation",
                "validation_rules": ["Code runs without errors", "Tests pass"],
            })
            steps.append({
                "objective": "Test and validate",
                "description": "Run tests and verify functionality",
                "priority": "medium",
                "risk_level": "low",
                "tools_allowed": ["test_run", "validation"],
                "expected_output": "Test results",
                "validation_rules": ["All tests pass", "No regressions"],
            })

        elif "analyze" in goal_lower or "review" in goal_lower:
            steps.append({
                "objective": f"Analyze: {goal}",
                "description": "Perform detailed analysis",
                "priority": "high",
                "risk_level": "low",
                "tools_allowed": ["analysis", "memory_search", "code_read"],
                "expected_output": "Analysis report",
                "validation_rules": ["Key findings identified", "Recommendations provided"],
            })

        else:
            # Generic single-step
            steps.append({
                "objective": goal,
                "description": context.get("description", "Execute goal"),
                "priority": "medium",
                "risk_level": "low",
                "tools_allowed": context.get("tools_allowed", []),
                "expected_output": context.get("expected_output", "Result"),
                "validation_rules": context.get("validation_rules", []),
            })

        return steps

    def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        return self._plans.get(plan_id)

    def update_plan_status(self, plan_id: str, status: str) -> bool:
        """Update plan status."""
        if plan_id in self._plans:
            self._plans[plan_id].status = status
            return True
        return False

    def list_plans(self, status: str | None = None) -> list[Plan]:
        """List all plans."""
        plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return plans
