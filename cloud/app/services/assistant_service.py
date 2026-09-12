"""Assistant provisioning for multi-assistant ops (6 phong + BGD).

Admin/BGĐ creates one virtual assistant per employee: a fresh API key plus an
ORG_ACL_JSON entry scoped to that person's function (phong/role), tasks and
work scope. Keys are returned ONCE at creation; the list endpoint only ever
exposes non-reversible key hints.

Persistence: MEMORY_API_KEYS + ORG_ACL_JSON are rewritten in cloud/.env and
settings are hot-reloaded in-process (get_settings.cache_clear). Valid only
for the single-process server (scripts/serve.ps1); multi-worker deployments
still need a restart.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from cloud.app.identity import (
    ORG_PROJECTS,
    ROLE_ADMIN,
    ROLE_BGD,
    ROLE_NHAN_VIEN,
    ROLE_TRUONG_PHONG,
    _default_projects,
    _default_tools,
    key_hint,
    slugify_user,
)

# Phongs that ordinary staff can belong to (shared company knowledge excluded).
STAFF_PHONGS: tuple[str, ...] = tuple(p for p in ORG_PROJECTS if p not in ("congty_chung", "bgd_rieng"))
VALID_ROLES: tuple[str, ...] = (ROLE_NHAN_VIEN, ROLE_TRUONG_PHONG, ROLE_BGD, ROLE_ADMIN)
VALID_POLICIES: tuple[str, ...] = ("local_only", "selective", "cloud_allowed")


class ProvisioningError(ValueError):
    """Invalid provisioning request (maps to 400/409 in the router)."""


def default_env_path() -> Path:
    """Absolute path of the server env file (never CWD-dependent)."""
    return Path(__file__).resolve().parents[3] / "cloud" / ".env"


def read_acl_entries() -> list[dict[str, Any]]:
    """Current raw entries from settings (empty list in open mode)."""
    from cloud.app.config import get_settings

    raw = (get_settings().org_acl_json or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [e for e in data] if isinstance(data, list) else []


def write_env_kv(env_path: Path, updates: dict[str, str]) -> None:
    """Rewrite KEY=VALUE pairs in a .env file, preserving everything else.

    Every existing `^KEY=` line is replaced (the file may contain duplicated
    blocks from start_all.ps1 appends); missing keys are appended once.
    """
    if not env_path.is_file():
        raise ProvisioningError(f"Env file not found: {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        replaced = False
        for k, v in updates.items():
            if line.startswith(f"{k}="):
                if k in pending:
                    out.append(f"{k}={v}")
                    del pending[k]
                # Duplicate occurrences collapse to the first replacement.
                replaced = True
                break
        if not replaced:
            out.append(line)
    for k, v in pending.items():
        out.append(f"{k}={v}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _persist(api_keys: list[str], entries: list[dict[str, Any]], env_path: Path | None) -> None:
    path = env_path or default_env_path()
    write_env_kv(path, {
        "MEMORY_API_KEYS": ",".join(api_keys),
        "ORG_ACL_JSON": json.dumps(entries, ensure_ascii=False),
    })
    # Hot-reload: settings are re-read from the file on next access.
    from cloud.app.config import get_settings
    from cloud.app.security import reset_limiters

    get_settings.cache_clear()
    reset_limiters()


def _normalize(user: str, phong: str, role: str) -> tuple[str, str, str]:
    slug = slugify_user(user)
    if not slug or slug == "unknown":
        raise ProvisioningError("Tên nhân viên không hợp lệ (user trống sau chuẩn hóa)")
    if role not in VALID_ROLES:
        raise ProvisioningError(f"role phải là một trong {list(VALID_ROLES)}")
    if role == ROLE_BGD:
        return slug, "bgd", role
    if role == ROLE_ADMIN:
        return slug, "admin", role
    if phong not in STAFF_PHONGS:
        raise ProvisioningError(f"phong phải là một trong {list(STAFF_PHONGS)} cho vai {role}")
    return slug, phong, role


def describe_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Public view of an assistant: everything except the raw key."""
    user = str(entry.get("user", "unknown"))
    phong = str(entry.get("phong", ""))
    role = str(entry.get("role", ROLE_NHAN_VIEN))
    reports = tuple(str(r) for r in (entry.get("reports") or []) if str(r).strip())
    projects = entry.get("projects") or list(_default_projects(user, phong, role, reports))
    tools = entry.get("tools") or list(_default_tools(phong, role))
    return {
        "user": user,
        "phong": phong,
        "role": role,
        "data_policy": str(entry.get("data_policy", "selective")),
        "reports": list(reports),
        "rate_limit": entry.get("rate_limit"),
        "projects_allowed": list(projects),
        "tools_allowed": list(tools),
        "key_hint": key_hint(str(entry.get("key", ""))) if entry.get("key") else "",
    }


def list_assistants() -> list[dict[str, Any]]:
    return [describe_entry(e) for e in read_acl_entries() if isinstance(e, dict)]


def provision_assistant(
    *,
    user: str,
    phong: str,
    role: str,
    data_policy: str = "selective",
    reports: list[str] | None = None,
    rate_limit: int | None = None,
    create_project: bool = True,
    env_path: Path | None = None,
) -> dict[str, Any]:
    """Create one assistant: fresh key + ACL entry (+ personal project).

    Returns the new API key ONCE — callers must display it immediately.
    Raises ProvisioningError on invalid input (400) or duplicates (409).
    """
    from cloud.app.config import get_settings
    from cloud.app.db import ProjectRecord, get_repository

    slug, phong_norm, role_norm = _normalize(user, phong, role)
    if data_policy not in VALID_POLICIES:
        raise ProvisioningError(f"data_policy phải là một trong {list(VALID_POLICIES)}")
    clean_reports = [str(r).strip() for r in (reports or []) if str(r).strip()]
    if rate_limit is not None and (not isinstance(rate_limit, int) or rate_limit < 1):
        raise ProvisioningError("rate_limit phải là số nguyên dương hoặc để trống")

    settings = get_settings()
    api_keys = [k for k in settings.api_key_list if k]
    entries = read_acl_entries()
    for e in entries:
        if isinstance(e, dict) and slugify_user(str(e.get("user", ""))) == slug:
            raise ProvisioningError(f"Trợ lý '{slug}' đã tồn tại (duplicate user)")

    fresh_key = "lt-" + secrets.token_urlsafe(24)
    entry: dict[str, Any] = {
        "key": fresh_key,
        "user": slug,
        "phong": phong_norm,
        "role": role_norm,
        "data_policy": data_policy,
    }
    if clean_reports:
        entry["reports"] = clean_reports
    if rate_limit is not None:
        entry["rate_limit"] = rate_limit
    entries.append(entry)
    api_keys.append(fresh_key)
    _persist(api_keys, entries, env_path)

    project_id: str | None = None
    if create_project and role_norm in (ROLE_NHAN_VIEN, ROLE_TRUONG_PHONG):
        repo = get_repository()
        name = f"nv_{slug}"
        rec = repo.find_project_by_name(name) or repo.create_project(
            ProjectRecord(name=name, description=f"Trợ lý cá nhân — {slug} ({phong_norm})",
                          metadata={"phong": phong_norm, "loai": "rieng", "owner": slug})
        )
        project_id = str(rec.id)

    view = describe_entry(entry)
    view["api_key"] = fresh_key  # shown ONCE
    view["project_id"] = project_id
    return view


def revoke_assistant(user: str, env_path: Path | None = None) -> dict[str, Any]:
    """Revoke one assistant's key (memories/projects are kept, access ends)."""
    from cloud.app.config import get_settings

    slug = slugify_user(user)
    settings = get_settings()
    entries = read_acl_entries()
    kept = [e for e in entries
            if not (isinstance(e, dict) and slugify_user(str(e.get("user", ""))) == slug)]
    if len(kept) == len(entries):
        raise ProvisioningError(f"Không tìm thấy trợ lý '{slug}'")
    removed_keys = {str(e.get("key")) for e in entries if isinstance(e, dict)} - \
        {str(e.get("key")) for e in kept if isinstance(e, dict)}
    api_keys = [k for k in settings.api_key_list if k not in removed_keys]
    _persist(api_keys, kept, env_path)
    return {"user": slug, "revoked": True}
