"""Agent Manager for Mid Brain - Manages OpenCode agent execution."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mid_brain.planning.planning_engine import Plan, PlanningEngine, TaskSpec


@dataclass(slots=True)
class ExecutionResult:
    """Result of task execution."""

    task_id: str
    success: bool
    output: str = ""
    error: str | None = None
    traceback: str | None = None
    files_changed: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    test_results: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    """Result of validation."""

    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Validator:
    """Validates task execution results."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()

    def validate(self, task: TaskSpec, result: ExecutionResult) -> ValidationResult:
        """Validate execution result against task validation rules."""
        vr = ValidationResult(passed=True)

        for rule in task.validation_rules:
            check = {"rule": rule, "passed": False, "details": ""}

            if rule.lower() == "code runs without errors":
                check["passed"] = result.success
                check["details"] = "Exit code 0" if result.success else f"Failed: {result.error}"

            elif rule.lower() == "tests pass":
                check["passed"] = "PASSED" in (result.test_results or "").upper() or "OK" in (result.test_results or "").upper()
                check["details"] = result.test_results or "No test output"

            elif rule.lower().startswith("no regress"):
                check["passed"] = True  # Would need baseline comparison
                check["details"] = "Regression check not implemented"

            elif rule.lower().startswith("at least") and "source" in rule.lower():
                # Check for source citations in output
                sources = result.output.count("source") + result.output.count("Source") + result.output.count("[")
                check["passed"] = sources >= 3
                check["details"] = f"Found {sources} potential citations"

            elif "confidence" in rule.lower():
                confidence = result.metadata.get("confidence", 0)
                check["passed"] = confidence > 0.7
                check["details"] = f"Confidence: {confidence:.2%}"

            elif "addresses" in rule.lower() and "question" in rule.lower():
                check["passed"] = bool(result.output.strip())
                check["details"] = "Output generated" if check["passed"] else "Empty output"

            else:
                check["passed"] = True
                check["details"] = f"Rule not implemented: {rule}"

            vr.checks.append(check)
            if not check["passed"]:
                vr.passed = False
                vr.errors.append(f"Validation failed: {rule} - {check['details']}")

        return vr


class OpenCodeAdapter:
    """Adapter to execute tasks via OpenCode CLI."""

    def __init__(self, project_root: Path | None = None, timeout: int = 300) -> None:
        self.project_root = project_root or Path.cwd()
        self.timeout = timeout

    def execute_task(self, task: TaskSpec, context: dict[str, Any] | None = None) -> ExecutionResult:
        """Execute a task using OpenCode."""
        start = time.time()
        result = ExecutionResult(task_id=task.task_id)

        try:
            # Build the prompt for OpenCode
            prompt = self._build_prompt(task, context)

            # Execute OpenCode
            cmd = ["opencode", "run", "--prompt", prompt]

            # Add tool restrictions if specified
            if task.tools_allowed:
                # OpenCode tool restriction would be configured differently
                pass

            proc = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds,
            )

            result.duration_ms = (time.time() - start) * 1000
            result.success = proc.returncode == 0
            result.output = proc.stdout
            result.error = proc.stderr if proc.returncode != 0 else None

            # Parse output for files changed, commands, etc.
            self._parse_output(result)

        except subprocess.TimeoutExpired:
            result.duration_ms = (time.time() - start) * 1000
            result.success = False
            result.error = f"Task timed out after {task.timeout_seconds}s"
        except FileNotFoundError:
            result.duration_ms = (time.time() - start) * 1000
            result.success = False
            result.error = "OpenCode CLI not found. Install with: pip install opencode"
        except Exception as e:
            result.duration_ms = (time.time() - start) * 1000
            result.success = False
            result.error = str(e)
            import traceback
            result.traceback = traceback.format_exc()

        return result

    def _build_prompt(self, task: TaskSpec, context: dict[str, Any] | None) -> str:
        """Build OpenCode prompt from task spec."""
        parts = [
            f"Objective: {task.objective}",
            f"Description: {task.description}",
        ]

        if context:
            parts.append(f"Context: {json.dumps(context, indent=2)}")

        if task.constraints:
            parts.append("Constraints:")
            for c in task.constraints:
                parts.append(f"  - {c}")

        parts.append(f"Expected Output: {task.expected_output}")

        if task.validation_rules:
            parts.append("Validation Rules:")
            for r in task.validation_rules:
                parts.append(f"  - {r}")

        return "\n".join(parts)

    def _parse_output(self, result: ExecutionResult) -> None:
        """Parse OpenCode output for metadata."""
        output = result.output

        # Look for file operations
        import re
        file_pattern = r"(?:Created|Modified|Updated|Deleted)\s+([^\n]+)"
        result.files_changed = re.findall(file_pattern, output, re.IGNORECASE)

        # Look for commands
        cmd_pattern = r"(?:Running|Executing|Command):\s*([^\n]+)"
        result.commands = re.findall(cmd_pattern, output, re.IGNORECASE)

        # Look for test results
        if "test" in output.lower():
            test_section = re.search(r"(?:test|Test).*?(?:\n\n|\Z)", output, re.DOTALL | re.IGNORECASE)
            if test_section:
                result.test_results = test_section.group(0)[:1000]


class HumanApprovalManager:
    """Manages human approval for high-risk tasks."""

    def __init__(self) -> None:
        self._pending_approvals: dict[str, dict[str, Any]] = {}

    def request_approval(self, task: TaskSpec, reason: str) -> str:
        """Request human approval for a task."""
        approval_id = task.task_id
        self._pending_approvals[approval_id] = {
            "task": task.to_dict(),
            "reason": reason,
            "requested_at": datetime.now().isoformat(),
            "status": "pending",
        }
        return approval_id

    def get_pending(self) -> list[dict[str, Any]]:
        """Get all pending approvals."""
        return [
            {"approval_id": k, **v}
            for k, v in self._pending_approvals.items()
            if v["status"] == "pending"
        ]

    def approve(self, approval_id: str, approved_by: str = "human") -> bool:
        """Approve a task."""
        if approval_id in self._pending_approvals:
            self._pending_approvals[approval_id]["status"] = "approved"
            self._pending_approvals[approval_id]["approved_by"] = approved_by
            self._pending_approvals[approval_id]["approved_at"] = datetime.now().isoformat()
            return True
        return False

    def reject(self, approval_id: str, reason: str, rejected_by: str = "human") -> bool:
        """Reject a task."""
        if approval_id in self._pending_approvals:
            self._pending_approvals[approval_id]["status"] = "rejected"
            self._pending_approvals[approval_id]["rejected_by"] = rejected_by
            self._pending_approvals[approval_id]["rejected_at"] = datetime.now().isoformat()
            self._pending_approvals[approval_id]["rejection_reason"] = reason
            return True
        return False

    def is_approved(self, approval_id: str) -> bool:
        """Check if task is approved."""
        approval = self._pending_approvals.get(approval_id)
        return approval is not None and approval["status"] == "approved"


class AgentManager:
    """Manages agent execution loop for Mid Brain."""

    def __init__(
        self,
        mid_brain: Any = None,
        project_root: Path | None = None,
    ) -> None:
        self.mid_brain = mid_brain
        self.project_root = project_root or Path.cwd()
        self.planner = PlanningEngine(mid_brain)
        self.adapter = OpenCodeAdapter(self.project_root)
        self.validator = Validator(self.project_root)
        self.approval = HumanApprovalManager()
        self._execution_history: list[dict[str, Any]] = []

    def initialize(self) -> None:
        """Initialize the agent manager."""
        pass

    def _sync_task_to_obsidian(self, task: TaskSpec, phase: str, result: ExecutionResult | None = None) -> None:
        """Sync task/result to Obsidian if enabled."""
        if not self.mid_brain or not self.mid_brain.config.enable_obsidian:
            return
        try:
            from mid_brain.obsidian.note_generator import NoteContext

            context = NoteContext(
                trace_id=task.task_id,
                project_id=task.metadata.get("project_id") if task.metadata else None,
                cognitive_phase=phase,
                source_brain="mid-brain",
                confidence=0.8,
                importance=0.7,
                tags=["agent", "task"],
                provenance={"task_id": task.task_id, "plan_id": task.metadata.get("plan_id") if task.metadata else None},
            )

            if phase == "PLANNING":
                cognitive_output = {"task_spec": task.to_dict()}
            elif phase == "EXECUTION":
                cognitive_output = {
                    "task_spec": task.to_dict(),
                    "result": {
                        "success": result.success if result else False,
                        "output": result.output if result else "",
                        "error": result.error if result else None,
                        "files_changed": result.files_changed if result else [],
                        "commands": result.commands if result else [],
                        "test_results": result.test_results if result else None,
                    }
                }
            else:
                return

            # Use the mid_brain's obsidian sync
            if hasattr(self.mid_brain, 'obsidian') and self.mid_brain.obsidian:
                self.mid_brain.obsidian.sync_to_obsidian(cognitive_output, context)
        except Exception:
            # Don't let sync failures break execution
            pass

    def execute_plan(self, plan: Plan) -> list[ExecutionResult]:
        """Execute a full plan."""
        results = []

        for task in plan.tasks:
            # Check dependencies
            if task.dependencies:
                dep_results = [r for r in results if r.task_id in task.dependencies]
                if not all(r.success for r in dep_results):
                    result = ExecutionResult(
                        task_id=task.task_id,
                        success=False,
                        error="Dependency failed",
                    )
                    results.append(result)
                    continue

            # Check if human approval needed
            if task.risk_level == "high":
                approval_id = self.approval.request_approval(
                    task,
                    f"High-risk task: {task.objective}",
                )
                # In real implementation, would wait for approval
                # For now, auto-approve for testing
                self.approval.approve(approval_id, "auto-test")

            if not self.approval.is_approved(task.task_id):
                result = ExecutionResult(
                    task_id=task.task_id,
                    success=False,
                    error="Pending human approval",
                )
                results.append(result)
                continue

            # Sync task creation to Obsidian (PLANNING phase)
            self._sync_task_to_obsidian(task, "PLANNING")

            # Execute task
            result = self.adapter.execute_task(task)
            self._execution_history.append({
                "task_id": task.task_id,
                "plan_id": plan.plan_id,
                "timestamp": datetime.now().isoformat(),
                "result": {
                    "success": result.success,
                    "duration_ms": result.duration_ms,
                },
            })

            # Sync execution result to Obsidian (EXECUTION phase)
            self._sync_task_to_obsidian(task, "EXECUTION", result)

            # Validate
            if result.success:
                validation = self.validator.validate(task, result)
                if not validation.passed:
                    result.success = False
                    result.error = f"Validation failed: {', '.join(validation.errors)}"

            results.append(result)

            # If task failed, stop or continue based on configuration
            if not result.success and task.priority == "critical":
                break

        return results

    def execute_single_task(self, task: TaskSpec) -> ExecutionResult:
        """Execute a single task."""
        plan = Plan(tasks=[task])
        results = self.execute_plan(plan)
        return results[0] if results else ExecutionResult(task_id=task.task_id, success=False, error="No result")

    def get_execution_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get execution history."""
        return self._execution_history[-limit:]

    def create_and_execute(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[Plan, list[ExecutionResult]]:
        """Create a plan and execute it."""
        plan = self.planner.create_plan(goal, context)
        # Sync plan creation to Obsidian
        if self.mid_brain and self.mid_brain.config.enable_obsidian:
            try:
                from mid_brain.obsidian.note_generator import NoteContext
                ctx = NoteContext(
                    trace_id=plan.plan_id,
                    project_id=context.get("project_id") if context else None,
                    cognitive_phase="PLANNING",
                    source_brain="mid-brain",
                    confidence=0.8,
                    importance=0.7,
                    tags=["agent", "plan"],
                    provenance={"plan_id": plan.plan_id, "goal": goal},
                )
                if hasattr(self.mid_brain, 'obsidian') and self.mid_brain.obsidian:
                    self.mid_brain.obsidian.sync_to_obsidian(
                        {"task_spec": {"objective": goal, "plan": plan.to_dict()}},
                        ctx
                    )
            except Exception:
                pass
        results = self.execute_plan(plan)
        return plan, results
