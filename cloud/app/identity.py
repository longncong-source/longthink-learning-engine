"""Org identity + project/tool ACL for multi-assistant deployment (6 phong + BGD).

Two modes:
  - OPEN (default, backward compatible): ORG_ACL_JSON empty -> resolve_identity
    returns None and every router behaves exactly as before. Existing tests run here.
  - CLOSED: each API key maps to an Identity; project_id and tool checks enforced.

Roles: nhan_vien | truong_phong | bgd | admin
  - bgd: sees everything ("*"), allowed code.execute / doc.delete / cloud.
  - admin: server ops only, local_only absolute, NO memory content access.
    Allowed tools: project.list/create, admin.audit/metrics. Everything else denied.
  - truong_phong: congty_chung + own phong_chung + knowledge.promote (propose up).
  - nhan_vien: congty_chung + own phong_chung + own nv_<user>.

Deferred to Phase 2 (noted, not silently allowed): truong_phong read-only into
nv_* of direct reports; cross-phong read requests; per-task tool sandboxing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

from cloud.app.config import get_settings

# Canonical org slugs (FINAL approved). Personal projects: nv_<slugified user>.
ORG_PROJECTS: tuple[str, ...] = (
    "congty_chung",
    "bgd_rieng",
    "phong_tchc_chung",
    "phong_tckt_chung",
    "phong_kthd_chung",
    "phong_ptda_chung",
    "phong_tkcn_chung",
    "phong_ktgs_chung",
)

ROLE_NHAN_VIEN = "nhan_vien"
ROLE_TRUONG_PHONG = "truong_phong"
ROLE_BGD = "bgd"
ROLE_ADMIN = "admin"

# Base tools every non-admin assistant gets; extended per phong/role below.
_BASE_TOOLS: tuple[str, ...] = (
    "memory.search",
    "memory.write",
    "doc.upload",
    "doc.read",
    "project.list",
    "midbrain.process",
    "midbrain.plan",
)
# Phongs allowed to run code/tasks (TKCN/KTGS/PTDA build & supervise).
_CODE_PHONGS = ("phong_tkcn_chung", "phong_ktgs_chung", "phong_ptda_chung")
_ADMIN_TOOLS: tuple[str, ...] = (
    "project.list",
    "project.create",
    "admin.audit",
    "admin.metrics",
    "watch.manage",
)


def key_hint(api_key: str) -> str:
    """Non-reversible 8-char hint safe for logs/audit."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:8]


def slugify_user(user: str) -> str:
    out = "".join(c if (c.isalnum() or c in ("_", "-")) else "_" for c in user.strip().lower())
    return "_".join(filter(None, out.split("_")))[:60] or "unknown"


@dataclass(slots=True)
class Identity:
    """One employee assistant (or ops principal). Never carries the raw API key."""

    user: str
    phong: str  # org slug, "bgd", or "admin"
    role: str
    projects_allowed: tuple[str, ...] = ()
    tools_allowed: tuple[str, ...] = ()
    data_policy: str = "selective"  # local_only | selective | cloud_allowed
    hint: str = ""
    reports: tuple[str, ...] = ()  # direct-report usernames (truong_phong read-only)
    rate_limit: int | None = None  # req/min override; None = server default

    @property
    def is_bgd(self) -> bool:
        return self.role == ROLE_BGD

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def effective_data_policy(self) -> str:
        # Admin is local_only absolute on the server — never exfiltrates.
        if self.is_admin:
            return "local_only"
        return self.data_policy


def _default_projects(
    user: str,
    phong: str,
    role: str,
    reports: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if role == ROLE_BGD:
        return ("*",)
    if role == ROLE_ADMIN:
        return ()
    personal = f"nv_{slugify_user(user)}"
    if role == ROLE_TRUONG_PHONG:
        # Read-only into direct reports' personal projects (write blocked separately).
        report_scopes = tuple(f"nv_{slugify_user(r)}" for r in reports)
        return ("congty_chung", phong, personal, *report_scopes)
    return ("congty_chung", phong, personal)


def is_foreign_personal(identity: Identity | None, project_name: str | None) -> bool:
    """True when a non-BGD writes into someone else's nv_* personal project.

    truong_phong may READ reports' nv_* (see _default_projects) but never WRITE.
    """
    if identity is None or identity.is_bgd or not project_name:
        return False
    if not project_name.startswith("nv_"):
        return False
    return project_name != f"nv_{slugify_user(identity.user)}"


def _default_tools(phong: str, role: str) -> tuple[str, ...]:
    if role == ROLE_BGD:
        return ("*",)
    if role == ROLE_ADMIN:
        return _ADMIN_TOOLS
    tools = list(_BASE_TOOLS)
    if phong in _CODE_PHONGS:
        tools.append("code.execute")
    if role == ROLE_TRUONG_PHONG:
        tools += ["knowledge.promote", "plan.execute"]
    return tuple(tools)


def _parse_acl() -> list[dict]:
    raw = (get_settings().org_acl_json or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def acl_configured() -> bool:
    return bool(_parse_acl())


def resolve_identity(api_key: str | None) -> Identity | None:
    """Map a raw API key to its Identity. None = open mode / unknown key.

    Unknown keys in closed mode are NOT silently allowed: routers that enforce
    ACL must treat (authenticated-but-unknown) as deny. require_api_key still
    rejects keys outside MEMORY_API_KEYS first, so unknown here means a valid
    key missing from ORG_ACL_JSON (misconfiguration) -> deny with clear error.
    """
    if not api_key or not acl_configured():
        return None
    for entry in _parse_acl():
        if not isinstance(entry, dict):
            continue
        candidate = str(entry.get("key", ""))
        if candidate and hmac.compare_digest(candidate, api_key):
            user = str(entry.get("user", "unknown"))
            phong = str(entry.get("phong", ""))
            role = str(entry.get("role", ROLE_NHAN_VIEN))
            raw_reports = entry.get("reports") or []
            reports = tuple(str(r) for r in raw_reports if str(r).strip())
            projects = entry.get("projects") or list(_default_projects(user, phong, role, reports))
            tools = entry.get("tools") or list(_default_tools(phong, role))
            policy = str(entry.get("data_policy", "selective"))
            rate_limit = entry.get("rate_limit")
            rate_limit = int(rate_limit) if isinstance(rate_limit, (int, float)) and rate_limit else None
            if phong == "admin" or role == ROLE_ADMIN:
                role, phong, reports = ROLE_ADMIN, "admin", ()
            return Identity(
                user=user,
                phong=phong,
                role=role,
                projects_allowed=tuple(projects),
                tools_allowed=tuple(tools),
                data_policy=policy,
                hint=key_hint(api_key),
                reports=reports,
                rate_limit=rate_limit,
            )
    return None


def _pattern_allowed(patterns: tuple[str, ...], name: str | None) -> bool:
    if "*" in patterns:
        return True
    if not name:
        return False
    for pat in patterns:
        if pat == name:
            return True
        if pat.endswith("*") and name.startswith(pat[:-1]):
            return True
    return False


def project_name_allowed(identity: Identity | None, project_name: str | None) -> bool:
    """Open mode (identity None) allows all. Closed mode matches slug patterns."""
    if identity is None:
        return True
    return _pattern_allowed(identity.projects_allowed, project_name)


def tool_allowed(identity: Identity | None, tool: str) -> bool:
    """Open mode allows all. Closed mode requires explicit tool grant."""
    if identity is None:
        return True
    return "*" in identity.tools_allowed or tool in identity.tools_allowed


def project_id_to_name(project_id: str | None, repo) -> str | None:  # type: ignore[no-untyped-def]
    """Best-effort id -> name resolution for ACL checks. None when unresolvable."""
    if not project_id:
        return None
    try:
        record = repo.get_project(str(project_id))
    except Exception:
        return None
    return record.name if record is not None else None


def check_project_id(
    identity: Identity | None,
    project_id: str | None,
    repo,  # type: ignore[no-untyped-def]
) -> str | None:
    """Return resolved project name if access granted, else None.

    Unresolvable ids (deleted/unknown project) are treated as deny in closed
    mode so a forged UUID can never bypass the ACL.
    """
    if identity is None:
        return project_id_to_name(project_id, repo) if project_id else None
    if not project_id:
        return None  # unscoped access handled by callers (bgd-only or post-filter)
    name = project_id_to_name(project_id, repo)
    if name is None:
        return None
    return name if project_name_allowed(identity, name) else None


def filter_names(names: list[str], identity: Identity | None) -> list[str]:
    """Keep only ACL-allowed project names (for post-filtering global queries)."""
    if identity is None:
        return names
    return [n for n in names if project_name_allowed(identity, n)]


def allowed_project_id_set(
    identity: Identity | None,
    repo,  # type: ignore[no-untyped-def]
) -> set[str] | None:
    """Project ids the identity may access. None = unrestricted (open mode/BGD).

    Memories without a project_id are never included -> unscoped content is
    BGD-only in closed mode (prevents cross-tenant leaks via global scope).
    """
    if identity is None or identity.is_bgd:
        return None
    try:
        all_projects = repo.list_projects(limit=1000)
    except Exception:
        return set()
    return {str(p.id) for p in all_projects if project_name_allowed(identity, p.name)}
