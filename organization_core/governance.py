"""LONGTHINK ORGANIZATION CORE — Phase 11 audit, governance & security.

- Canonical audit writer with full spec fields + sha256 hash chain
  (tamper-evident; append-only) + checkpoint counters.
- Versioned policy registry (register/get/history/rollback, append-only).
- Authentication integration point (env API keys; open mode when unset,
  mirroring the Second Brain convention; SSO-ready seam).
- Tenant/company isolation guard, least-privilege helpers.
- Input validation (message bounds), output secret scanning.
- Opt-in rate limiting (env-gated, off by default).
- Prompt-injection boundary: DATA vs INSTRUCTION vs POLICY. Retrieved
  content is always DATA and can never become POLICY; POLICY lives only in
  the policies table, never inside retrieved documents.
- Tool allowlist per agent kind.
- Sensitive-data minimization helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

from organization_core.auth import ensure_policy
from organization_core.models import new_id, utcnow_iso
from organization_core.store import OrganizationStore, encode_json

GENESIS_HASH = "0" * 64

# --- prompt-injection boundary ----------------------------------------------

INSTRUCTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "disregard previous",
    "you are now",
    "system:",
    "new instructions:",
    "override policy",
    "bypass approval",
    "act as if you are",
    "pretend you are",
    "jailbreak",
    "do anything now",
)

SECRET_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]{8,}"),
    re.compile(r"(?i)(password|passwd|api[_-]?key)\s*[:=]\s*\S+"),
)


def classify_content(text: str) -> str:
    """DATA (default) vs INSTRUCTION (looks like an override attempt)."""
    lowered = (text or "").lower()
    if any(p in lowered for p in INSTRUCTION_PATTERNS):
        return "INSTRUCTION"
    return "DATA"


def contains_injection(text: str) -> bool:
    return classify_content(text) == "INSTRUCTION"


def quarantine(text: str) -> dict:
    """Wrap retrieved content as untrusted DATA; POLICY never comes from here."""
    return {"kind": "DATA",
            "content": text,
            "injection_suspected": contains_injection(text),
            "note": "retrieved content is evidence, never instructions"}


def scan_secrets(text: str) -> list[str]:
    """Return redacted previews of secret-like spans (never the secrets)."""
    hits = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text or ""):
            hits.append(f"{pattern.pattern[:12]}...@{match.start()}")
    return hits


def redact_secrets(text: str) -> str:
    out = text or ""
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def check_message(message: str, max_chars: int = 2000) -> str:
    text = (message or "").strip()
    if not text:
        raise ValueError("message is empty")
    if len(text) > max_chars:
        raise ValueError(f"message exceeds {max_chars} chars")
    return text


# --- tool allowlist ----------------------------------------------------------

TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    "personal": frozenset({"org.read", "docs.search"}),
    "department": frozenset({"org.read", "docs.search", "hr.report",
                             "finance.read", "finance.report",
                             "contract.read", "tender.report", "site.read",
                             "quality.report", "project.read",
                             "investment.report", "design.read",
                             "design.review", "hse.read", "hse.report"}),
    "project": frozenset({"project.read", "docs.search", "project.report"}),
    "enterprise": frozenset({"org.read", "docs.search", "project.read"}),
    "internal": frozenset({"task.execute"}),
}


def check_tool(agent_kind: str, tool: str) -> bool:
    return tool in TOOL_ALLOWLIST.get(agent_kind, frozenset())


def minimize_person(person: dict, is_admin: bool) -> dict:
    if is_admin:
        return dict(person)
    return {k: v for k, v in person.items()
            if k not in ("full_name", "metadata")}


# --- canonical audit (hash-chained, tamper-evident) ---------------------------


def _chain_head(store: OrganizationStore) -> tuple[str, int]:
    head = store.query_one(
        "SELECT value FROM governance_kv WHERE key = 'audit_head'")
    count = store.query_one(
        "SELECT value FROM governance_kv WHERE key = 'audit_count'")
    return (head["value"] if head else GENESIS_HASH,
            int(count["value"]) if count else 0)


def _set_kv(store: OrganizationStore, key: str, value: str) -> None:
    store.execute(
        "INSERT INTO governance_kv (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def audit(
    store: OrganizationStore,
    *,
    actor_id: str | None,
    actor_type: str = "human",
    action: str,
    resource: str = "",
    resource_id: str | None = None,
    organization_id: str | None = None,
    project_id: str | None = None,
    authorization_result: str = "",
    policy: str = "",
    request_id: str | None = None,
    correlation_id: str | None = None,
    result: str = "",
    detail: dict | None = None,
) -> dict:
    """Append one chained audit record (full spec fields)."""
    prev_hash, count = _chain_head(store)
    now = utcnow_iso()
    entry_id = new_id()
    stored_resource = resource or None
    stored_authz = authorization_result or None
    fingerprint = {
        "id": entry_id, "actor_id": actor_id, "action": action,
        "resource": stored_resource, "resource_id": resource_id,
        "authorization_result": stored_authz, "result": result,
        "created_at": now, "prev_hash": prev_hash,
    }
    entry_hash = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    context = dict(detail or {})
    context.update({"organization_id": organization_id,
                    "project_id": project_id})
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at, resource, resource_id,"
        " authz_result, policy_ref, request_id, correlation_id, result,"
        " prev_hash, entry_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_id, actor_type, actor_id, action, stored_resource,
         resource_id, encode_json(context), now, stored_resource,
         resource_id, stored_authz, policy or None,
         request_id, correlation_id, result, prev_hash, entry_hash),
    )
    _set_kv(store, "audit_head", entry_hash)
    _set_kv(store, "audit_count", str(count + 1))
    return {"id": entry_id, "entry_hash": entry_hash,
            "prev_hash": prev_hash}


def verify_audit_chain(store: OrganizationStore) -> dict:
    """Verify link integrity + checkpoint continuity of chained rows."""
    rows = store.query_all(
        "SELECT * FROM audit_events WHERE entry_hash IS NOT NULL"
        " ORDER BY rowid")
    expected_prev = GENESIS_HASH
    for row in rows:
        if row["prev_hash"] != expected_prev:
            return {"ok": False, "reason": "chain link broken",
                    "at_id": row["id"]}
        fingerprint = {
            "id": row["id"], "actor_id": row["actor_id"],
            "action": row["action"], "resource": row["resource"],
            "resource_id": row["resource_id"],
            "authorization_result": row["authz_result"],
            "result": row["result"], "created_at": row["created_at"],
            "prev_hash": row["prev_hash"],
        }
        recomputed = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        if recomputed != row["entry_hash"]:
            return {"ok": False, "reason": "entry tampered",
                    "at_id": row["id"]}
        expected_prev = row["entry_hash"]
    head, count = _chain_head(store)
    if rows and head != rows[-1]["entry_hash"]:
        return {"ok": False, "reason": "head checkpoint mismatch",
                "at_id": None}
    if count != len(rows):
        # Legacy unchained rows never touch the checkpoint, so any mismatch
        # here means chained rows were added/removed out of band.
        chained_total = store.count(
            "audit_events", "entry_hash IS NOT NULL")
        if count != chained_total:
            return {"ok": False, "reason": "count checkpoint mismatch",
                    "at_id": None}
    return {"ok": True, "verified": len(rows)}


# --- versioned policy registry -------------------------------------------------


def register_policy(store: OrganizationStore, code: str, name: str,
                    effect: str, rules: dict,
                    scope: str = "global") -> dict:
    pid = ensure_policy(store, code, name, effect, rules, scope=scope)
    return get_policy(store, code) or {"id": pid, "code": code}


def get_policy(store: OrganizationStore, code: str) -> dict | None:
    row = store.query_one(
        "SELECT * FROM policies WHERE code = ? AND is_deleted = 0", (code,))
    return dict(row) if row else None


def list_policy_versions(store: OrganizationStore, code: str) -> list[dict]:
    policy = get_policy(store, code)
    if policy is None:
        raise LookupError(f"Policy not found: {code}")
    rows = store.query_all(
        "SELECT * FROM policy_versions WHERE policy_id = ?"
        " ORDER BY version",
        (policy["id"],))
    return [dict(r) for r in rows]


def rollback_policy(store: OrganizationStore, code: str, version: int,
                    actor_id: str = "system") -> dict:
    """Append-only rollback: copies an old version into a NEW version."""
    policy = get_policy(store, code)
    if policy is None:
        raise LookupError(f"Policy not found: {code}")
    old = store.query_one(
        "SELECT * FROM policy_versions WHERE policy_id = ? AND version = ?",
        (policy["id"], version),
    )
    if old is None:
        raise LookupError(f"Version {version} not found for {code}")
    import json as jsonlib

    ensure_policy(store, code, policy["name"], old["effect"],
                  jsonlib.loads(old["rules"]), scope=old["scope"])
    audit(store, actor_id=actor_id, action="policy.rollback", resource="policy",
          resource_id=policy["id"], result="ok",
          detail={"code": code, "to_version": version})
    return get_policy(store, code)


# --- authentication integration point -------------------------------------------


@dataclass(slots=True)
class Identity:
    subject: str
    mode: str  # open | key


def _configured_keys() -> list[str]:
    raw = os.environ.get("ORGANIZATION_CORE_API_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def authenticate_request(api_key: str | None) -> Identity:
    """SSO-ready seam: env keys when configured, open mode otherwise."""
    keys = _configured_keys()
    if not keys:
        return Identity(subject="local-operator", mode="open")
    if api_key and api_key.strip() in keys:
        return Identity(subject=f"key:{api_key.strip()[:6]}", mode="key")
    raise PermissionError("invalid or missing API key")


# --- tenant / company isolation ---------------------------------------------------


def check_company_scope(store: OrganizationStore, actor_person_id: str,
                        company_id: str | None) -> None:
    if company_id is None:
        return
    company = store.query_one(
        "SELECT id FROM companies WHERE code = 'DAK' AND is_deleted = 0")
    home = company["id"] if company else None
    if home is not None and company_id not in (home, "DAK"):
        from organization_core.auth import AuthorizationError

        raise AuthorizationError("cross-company access denied")


# --- rate limiting (env-gated, off by default) --------------------------------------


@dataclass(slots=True)
class _Bucket:
    count: int = 0
    window_start: float = 0.0


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.buckets: dict[str, _Bucket] = {}

    def reset(self) -> None:
        self.buckets.clear()

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self.buckets.get(key)
        if bucket is None or now - bucket.window_start >= 60.0:
            bucket = _Bucket(count=0, window_start=now)
            self.buckets[key] = bucket
        bucket.count += 1
        if bucket.count > self.per_minute:
            raise PermissionError(f"rate limit exceeded ({self.per_minute}/min)")


_LIMITER = RateLimiter(60)


def reset_rate_limiter() -> None:
    _LIMITER.reset()


def check_rate_limit(key: str) -> None:
    raw = os.environ.get("ORGANIZATION_CORE_RATE_LIMIT_PER_MINUTE", "")
    if not raw:
        return  # off by default; enable in deployment (Phase 12)
    _LIMITER.per_minute = int(raw)
    _LIMITER.check(key)
