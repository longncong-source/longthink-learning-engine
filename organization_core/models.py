"""LONGTHINK ORGANIZATION CORE — Phase 01 domain model (dataclasses).

Independent from KNOWLEDGE CORE / INTELLIGENCE CORE.
No direct DB access to other cores — only via adapters (Phase 08+).
Position and Person are independent entities (master rule 7).
No real personal names are hard-coded anywhere in this package.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class BaseEntity:
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    is_deleted: int = 0

    def to_dict(self) -> dict:
        return dict(asdict(self))


@dataclass(slots=True)
class Company(BaseEntity):
    code: str = ""
    name: str = ""
    status: str = "active"


@dataclass(slots=True)
class Department(BaseEntity):
    company_id: str = ""
    code: str = ""
    name: str = ""
    dept_type: str = "functional"  # board | functional
    status: str = "active"
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(slots=True)
class Team(BaseEntity):
    department_id: str = ""
    code: str = ""
    name: str = ""
    status: str = "active"
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(slots=True)
class Position(BaseEntity):
    department_id: str | None = None
    code: str = ""
    title: str = ""
    level: str = "staff"
    authority_scope: dict = field(default_factory=dict)
    headcount_baseline: int = 0
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(slots=True)
class Person(BaseEntity):
    code: str = ""
    full_name: str = ""
    status: str = "active"


@dataclass(slots=True)
class Role(BaseEntity):
    code: str = ""
    name: str = ""
    description: str | None = None


@dataclass(slots=True)
class Permission(BaseEntity):
    code: str = ""
    action: str = ""
    resource: str = ""
    description: str | None = None


@dataclass(slots=True)
class Delegation(BaseEntity):
    from_person_id: str = ""
    to_person_id: str = ""
    scope: dict = field(default_factory=dict)
    status: str = "active"
    effective_from: str | None = None
    effective_to: str | None = None
    policy_ref: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class Project(BaseEntity):
    code: str = ""
    name: str = ""
    status: str = "active"


@dataclass(slots=True)
class ProjectRole(BaseEntity):
    code: str = ""
    name: str = ""
    authority_level: int = 0


@dataclass(slots=True)
class ProjectAssignment(BaseEntity):
    project_id: str = ""
    person_id: str = ""
    project_role_id: str | None = None
    status: str = "active"
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(slots=True)
class Task(BaseEntity):
    project_id: str | None = None
    assignee_person_id: str | None = None
    title: str = ""
    status: str = "open"
    priority: str = "normal"
    due_at: str | None = None


@dataclass(slots=True)
class Workflow(BaseEntity):
    code: str = ""
    name: str = ""
    version: int = 1
    definition: dict = field(default_factory=dict)
    status: str = "active"


@dataclass(slots=True)
class WorkflowInstance(BaseEntity):
    workflow_id: str = ""
    business_ref_type: str | None = None
    business_ref_id: str | None = None
    status: str = "running"
    current_step: str | None = None


@dataclass(slots=True)
class Approval(BaseEntity):
    workflow_instance_id: str | None = None
    requester_person_id: str | None = None
    approver_person_id: str | None = None
    approver_role_id: str | None = None
    action: str = ""
    status: str = "pending"
    decided_at: str | None = None
    policy_ref: str | None = None


@dataclass(slots=True)
class Assistant(BaseEntity):
    kind: str = "personal"  # personal | department | project | enterprise
    name: str = ""
    owner_person_id: str | None = None
    department_id: str | None = None
    project_id: str | None = None
    config: dict = field(default_factory=dict)
    status: str = "active"


@dataclass(slots=True)
class Agent(BaseEntity):
    kind: str = "department"  # department | project | enterprise | internal
    name: str = ""
    ref_type: str | None = None
    ref_id: str | None = None
    config: dict = field(default_factory=dict)
    status: str = "active"


@dataclass(slots=True)
class Policy(BaseEntity):
    code: str = ""
    name: str = ""
    rules: dict = field(default_factory=dict)
    effect: str = "allow"  # allow | deny | require_approval
    status: str = "active"
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(slots=True)
class AuditEvent:
    action: str = ""
    actor_type: str | None = None
    actor_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    context: dict = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict:
        return dict(asdict(self))


@dataclass(slots=True)
class Risk(BaseEntity):
    project_id: str | None = None
    title: str = ""
    severity: str = "medium"
    status: str = "open"


@dataclass(slots=True)
class Issue(BaseEntity):
    project_id: str | None = None
    title: str = ""
    status: str = "open"


@dataclass(slots=True)
class Decision(BaseEntity):
    project_id: str | None = None
    title: str = ""
    content: str = ""
    status: str = "draft"
