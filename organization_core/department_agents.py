"""LONGTHINK ORGANIZATION CORE — Phase 05 Department Agents.

Seven functional agents (TCHC/TCKT/KTHD/KTGS/PTDA/TKCN/AT), each with:
agent_id, department_id, mandate, responsibilities, allowed_tools,
knowledge_scope, routing_rules, approval_rules, escalation_rules.

Personal Assistant routes domain questions to the owning agent; cross-
department tasks go through a Coordinator that aggregates scoped answers.
No agent may exceed its authority: coordination is read-only Q&A, execution
always returns to the assistant chat flow (Phase 04) with authorization.
"""

from __future__ import annotations

from organization_core.adapters import AdapterBundle
from organization_core.auth import AuthorizationError
from organization_core.models import new_id, utcnow_iso
from organization_core.observability import inc as obs_inc
from organization_core.store import OrganizationStore, decode_json, encode_json

AGENT_ORDER = ("TCHC", "TCKT", "KTHD", "KTGS", "PTDA", "TKCN", "AT")


def _spec(dept_code: str, mandate: str, responsibilities: list[str],
          allowed_tools: list[str], knowledge_scope: list[str],
          keywords: list[str], approval_rules: dict,
          escalation_rules: dict) -> dict:
    return {
        "agent_code": f"{dept_code}_AGENT",
        "department_code": dept_code,
        "mandate": mandate,
        "responsibilities": responsibilities,
        "allowed_tools": allowed_tools,
        "knowledge_scope": knowledge_scope,
        "routing_rules": {"keywords": keywords},
        "approval_rules": approval_rules,
        "escalation_rules": escalation_rules,
    }


AGENT_SPECS: dict[str, dict] = {
    "TCHC": _spec(
        "TCHC", "To chuc, nhan su, hanh chinh va van phong DAK.",
        ["organization", "HR", "training", "labor/pay", "administration",
         "archive", "IT/admin support", "legal/comms interface"],
        ["org.read", "docs.search", "hr.report"],
        ["HR", "administration", "labor", "training", "archive"],
        ["nhân sự", "nhan su", "hr", "tuyển dụng", "tuyen dung", "đào tạo",
         "dao tao", "training", "lương", "luong", "labor", "hành chính",
         "hanh chinh", "lưu trữ", "luu tru", "archive", "pháp chế",
         "phap che", "legal", "văn phòng", "van phong"],
        {"self_approve": False, "requires": "BGD for headcount changes"},
        {"to": "BGD", "when": "headcount, policy, or labor dispute"},
    ),
    "TCKT": _spec(
        "TCKT", "Ke toan, tai chinh, thue va tai san DAK.",
        ["accounting", "finance", "tax", "statistics", "fixed assets",
         "operating/service costs"],
        ["finance.read", "docs.search", "finance.report"],
        ["finance", "accounting", "tax", "assets"],
        ["tài chính", "tai chinh", "finance", "kế toán", "ke toan",
         "accounting", "thuế", "thue", "tax", "thống kê", "thong ke",
         "tài sản", "tai san", "fixed asset", "doanh thu", "revenue",
         "chi phí vận hành", "operating cost"],
        {"self_approve": False, "requires": "BGD for payments"},
        {"to": "BGD", "when": "payment, budget overrun, or tax issue"},
    ),
    "KTHD": _spec(
        "KTHD", "Quan ly chi phi, dau thau, hop dong va mua sam DAK.",
        ["cost management", "tendering", "contracts", "procurement",
         "planning", "budget", "settlement"],
        ["contract.read", "docs.search", "tender.report"],
        ["contracts", "tendering", "procurement", "budget"],
        ["hợp đồng", "hop dong", "contract", "đấu thầu", "dau thau",
         "tender", "mua sắm", "mua sam", "procurement", "quyết toán",
         "quyet toan", "settlement", "ngân sách", "ngan sach", "budget",
         "đơn giá", "don gia"],
        {"self_approve": False, "requires": "BGD for contract signing"},
        {"to": "BGD", "when": "contract award, claim, or over-budget"},
    ),
    "KTGS": _spec(
        "KTGS", "Giam sat ky thuat, chat luong, khoi luong, tien do DAK.",
        ["technical supervision", "quality", "quantity", "schedule",
         "design review", "technical documents",
         "construction/commissioning coordination"],
        ["site.read", "docs.search", "quality.report"],
        ["supervision", "quality", "schedule", "construction"],
        ["giám sát", "giam sat", "supervision", "chất lượng", "chat luong",
         "quality", "khối lượng", "khoi luong", "tiến độ", "tien do",
         "schedule", "thẩm định", "tham dinh", "thi công", "thi cong",
         "construction", "nghiệm thu", "nghiem thu", "commissioning"],
        {"self_approve": False, "requires": "TKCN for design changes"},
        {"to": "BGD", "when": "quality failure or schedule slip"},
    ),
    "PTDA": _spec(
        "PTDA", "Phat trien du an va co hoi dau tu DAK.",
        ["investment opportunity", "project preparation",
         "investment planning", "risk/environment/safety coordination",
         "tender/negotiation coordination", "project development"],
        ["project.read", "docs.search", "investment.report"],
        ["investment", "project development", "planning"],
        ["đầu tư", "dau tu", "investment", "cơ hội", "co hoi",
         "dự án mới", "du an moi", "project development",
         "chuẩn bị dự án", "chuan bi du an", "khả thi", "kha thi",
         "feasibility", "quy hoạch", "quy hoach"],
        {"self_approve": False, "requires": "BGD for investment decision"},
        {"to": "BGD", "when": "investment approval or major risk"},
    ),
    "TKCN": _spec(
        "TKCN", "Thiet ke, cong nghe va ho tro ky thuat EPC DAK.",
        ["design", "technology", "scope/design tasks", "technical review",
         "EPC/construction engineering support", "R&D"],
        ["design.read", "docs.search", "design.review"],
        ["design", "technology", "engineering", "R&D"],
        ["thiết kế", "thiet ke", "design", "công nghệ", "cong nghe",
         "technology", "epc", "r&d", "nghiên cứu", "nghien cuu",
         "bản vẽ", "ban ve", "drawing", "giải pháp kỹ thuật",
         "giai phap ky thuat"],
        {"self_approve": False, "requires": "KTGS for site application"},
        {"to": "BGD", "when": "design change with cost/schedule impact"},
    ),
    "AT": _spec(
        "AT", "An toan, suc khoe, moi truong va tuan thu HSEQ DAK.",
        ["security", "safety", "quality", "environment",
         "fire prevention/firefighting", "ISO 9001/14001/45001",
         "HSEQ/QA compliance"],
        ["hse.read", "docs.search", "hse.report"],
        ["safety", "HSEQ", "environment", "ISO", "fire"],
        ["an toàn", "an toan", "safety", "bảo hộ", "bao ho", "môi trường",
         "moi truong", "environment", "pccc", "cháy", "chay", "fire",
         "iso", "hseq", "qa", "sự cố", "su co", "incident", "bảo vệ",
         "bao ve", "security"],
        {"self_approve": False, "requires": "BGD for work stoppage"},
        {"to": "BGD", "when": "incident, stop-work, or non-compliance"},
    ),
}

REQUIRED_SPEC_KEYS = ("agent_code", "mandate", "responsibilities",
                      "allowed_tools", "knowledge_scope", "routing_rules",
                      "approval_rules", "escalation_rules")


def ensure_department_agents(store: OrganizationStore) -> list[dict]:
    """Create/update the 7 department agent rows. Idempotent."""
    agents = []
    for code in AGENT_ORDER:
        spec = AGENT_SPECS[code]
        dept = store.query_one(
            "SELECT id FROM departments WHERE code = ? AND is_deleted = 0",
            (code,),
        )
        if dept is None:
            raise LookupError(f"Department not seeded: {code}")
        now = utcnow_iso()
        existing = store.query_one(
            "SELECT * FROM agents WHERE kind = 'department'"
            " AND ref_type = 'department' AND ref_id = ? AND is_deleted = 0",
            (dept["id"],),
        )
        if existing:
            store.execute(
                "UPDATE agents SET name = ?, config = ?, status = 'active',"
                " updated_at = ? WHERE id = ?",
                (spec["agent_code"], encode_json(spec), now, existing["id"]),
            )
            row = store.query_one("SELECT * FROM agents WHERE id = ?",
                                  (existing["id"],))
        else:
            aid = new_id()
            store.execute(
                "INSERT INTO agents (id, kind, name, ref_type, ref_id, config,"
                " status, created_at, updated_at, is_deleted)"
                " VALUES (?, 'department', ?, 'department', ?, ?, 'active',"
                " ?, ?, 0)",
                (aid, spec["agent_code"], dept["id"], encode_json(spec),
                 now, now),
            )
            row = store.query_one("SELECT * FROM agents WHERE id = ?", (aid,))
        item = dict(row)
        item["config"] = decode_json(item.get("config"))
        item["department_id"] = dept["id"]
        agents.append(item)
    return agents


def get_department_agent(store: OrganizationStore, dept_code: str) -> dict:
    if dept_code not in AGENT_SPECS:
        raise LookupError(f"Unknown department agent: {dept_code}")
    agents = ensure_department_agents(store)
    return next(a for a in agents
                if a["config"]["department_code"] == dept_code)


def _score(message: str, keywords: list[str]) -> int:
    lowered = message.lower()
    return sum(1 for k in keywords if k in lowered)


def route_to_agent(
    store: OrganizationStore,
    message: str,
    candidates: list[str] | None = None,
) -> dict:
    """Score message against routing rules. Never raises on no-match."""
    wanted = candidates or list(AGENT_ORDER)
    unknown = [c for c in wanted if c not in AGENT_SPECS]
    if unknown:
        raise LookupError(f"Unknown department agent: {unknown[0]}")
    scored = sorted(
        ((code, _score(message, AGENT_SPECS[code]["routing_rules"]["keywords"]))
         for code in wanted),
        key=lambda item: (-item[1], AGENT_ORDER.index(item[0])),
    )
    best_code, best_score = scored[0]
    obs_inc("org_agent_routing_total",
            {"agent": best_code if best_score > 0 else "none"})
    return {
        "agent_code": f"{best_code}_AGENT" if best_score > 0 else None,
        "department_code": best_code if best_score > 0 else None,
        "score": best_score,
        "alternatives": [
            {"agent_code": f"{c}_AGENT", "score": s}
            for c, s in scored[1:4] if s > 0
        ],
    }


def agent_handles(store: OrganizationStore, dept_code: str,
                  message: str) -> bool:
    """Scope check: does this agent own the message topic?"""
    if dept_code not in AGENT_SPECS:
        raise LookupError(f"Unknown department agent: {dept_code}")
    return _score(message,
                  AGENT_SPECS[dept_code]["routing_rules"]["keywords"]) > 0


def coordinate(
    store: OrganizationStore,
    actor_person_id: str,
    message: str,
    agent_codes: list[str] | None = None,
    adapters: AdapterBundle | None = None,
) -> dict:
    """Coordinator fan-out for cross-department tasks (read-only aggregate).

    Execution intents are refused here — they must go through the Personal
    Assistant chat flow with authorization (no agent exceeds authority).
    """
    from organization_core.assistant import detect_intent  # local, avoids cycle

    adapters = adapters or AdapterBundle.mocks()
    from organization_core import governance as gov_module

    message = gov_module.check_message(message)
    actor = store.query_one(
        "SELECT id FROM persons WHERE id = ? AND status = 'active'"
        " AND is_deleted = 0",
        (actor_person_id,),
    )
    if actor is None:
        raise AuthorizationError("unknown or inactive actor")
    intent = detect_intent(message)
    if intent in ("execution", "approval", "org_mutation"):
        _audit_coord(store, actor_person_id, agent_codes or [], False, intent)
        return {"authorized": False, "intent": intent, "contributions": [],
                "reply": "Coordinator only aggregates knowledge; consequential"
                         " actions must go through your Personal Assistant."}
    if agent_codes is None:
        routed = route_to_agent(store, message)
        agent_codes = ([routed["department_code"]] if routed["department_code"]
                       else ["TCHC"])
    contributions = []
    for code in agent_codes:
        if code not in AGENT_SPECS:
            raise LookupError(f"Unknown department agent: {code}")
        spec = AGENT_SPECS[code]
        scoped = adapters.intelligence.ask(
            message, {"agent": spec["agent_code"], "mandate": spec["mandate"]})
        contributions.append({
            "agent_code": spec["agent_code"],
            "department_code": code,
            "mandate": spec["mandate"],
            "answer": scoped["answer"],
            "in_scope": agent_handles(store, code, message),
        })
    reply = " | ".join(c["agent_code"] + ": " + c["answer"]
                       for c in contributions)
    _audit_coord(store, actor_person_id, agent_codes, True, intent)
    return {"authorized": True, "intent": intent,
            "contributions": contributions, "reply": reply}


def _audit_coord(store, actor_id, agents, allow, note) -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, 'agent.coordinate', 'agent', NULL, ?, ?)",
        (new_id(), actor_id,
         encode_json({"agents": agents, "allow": allow, "note": note}),
         utcnow_iso()),
    )
