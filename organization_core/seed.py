"""DAK organization seed — Phase 01 baseline, extended in Phase 03.

Seeds Company DAK + Board of Directors (BGD) + 7 functional departments +
position templates. Time-variable via effective_from; templates carry
headcount_baseline (NOT current headcount). No real personal names.
Idempotent: safe to run multiple times.
"""

from __future__ import annotations

from organization_core.models import new_id, utcnow_iso
from organization_core.store import OrganizationStore, encode_json

COMPANY_CODE = "DAK"
COMPANY_NAME = "DAK"

BOARD_DEPT = ("BGD", "Ban Giam doc", "board")

DEPARTMENTS: tuple[tuple[str, str], ...] = (
    ("TCHC", "To chuc Hanh chinh"),
    ("TCKT", "Tai chinh Ke toan"),
    ("KTHD", "Kinh te Hop dong"),
    ("KTGS", "Ky thuat Giam sat"),
    ("PTDA", "Phat trien Du an"),
    ("TKCN", "Thiet ke va Cong nghe"),
    ("AT", "An toan"),
)

# (position_code, title, level, headcount_baseline)
BOARD_POSITIONS: tuple[tuple[str, str, str, int], ...] = (
    ("DAK-BGD-GD", "Giam doc", "executive", 1),
    ("DAK-BGD-PGD", "Pho Giam doc", "executive", 2),
)

# Per functional department: truong/pho/chuyen vien templates.
DEPT_POSITION_TEMPLATES: tuple[tuple[str, str, int], ...] = (
    ("TP", "Truong phong", 1),
    ("PP", "Pho phong", 1),
    ("CV", "Chuyen vien", 0),
)

# Phase 03: professional-track templates (independent of headcount).
# Codes: KSC=Ky su chinh, KS=Ky su, CS=Can su, NV=Nhan vien.
DEPT_TECHNICAL_TEMPLATES: tuple[tuple[str, str, int], ...] = (
    ("KSC", "Ky su chinh", 0),
    ("KS", "Ky su", 0),
    ("CS", "Can su", 0),
    ("NV", "Nhan vien", 0),
)

# TCKT extras: TQ=Thu quy.
TCKT_EXTRA_TEMPLATES: tuple[tuple[str, str, int], ...] = (
    ("TQ", "Thu quy", 1),
)

ORG_VERSION = "v2026.01"
ORG_VERSION_LABEL = "Co cau DAK — ban dau (Ban Giam doc + 7 phong chuc nang)"


def _get_id(store: OrganizationStore, table: str, code: str) -> str | None:
    row = store.query_one(f"SELECT id FROM {table} WHERE code = ?", (code,))
    return row["id"] if row else None


def seed_dak(store: OrganizationStore) -> dict:
    """Insert DAK baseline if missing. Returns counts of key tables."""
    now = utcnow_iso()
    store.init_schema()

    company_id = _get_id(store, "companies", COMPANY_CODE)
    if company_id is None:
        company_id = new_id()
        store.execute(
            "INSERT INTO companies (id, code, name, status, created_at,"
            " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
            (company_id, COMPANY_CODE, COMPANY_NAME, now, now),
        )

    dept_ids: dict[str, str] = {}
    all_depts: list[tuple[str, str]] = [(BOARD_DEPT[0], BOARD_DEPT[1])]
    all_depts += [(c, n) for c, n in DEPARTMENTS]
    for code, name in all_depts:
        existing = _get_id(store, "departments", code)
        if existing is not None:
            dept_ids[code] = existing
            continue
        dept_id = new_id()
        dept_type = "board" if code == "BGD" else "functional"
        store.execute(
            "INSERT INTO departments (id, company_id, code, name, dept_type,"
            " status, effective_from, effective_to, created_at, updated_at,"
            " is_deleted) VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, ?, ?, 0)",
            (dept_id, company_id, code, name, dept_type, now, now, now),
        )
        dept_ids[code] = dept_id

    for code, title, level, baseline in BOARD_POSITIONS:
        if _get_id(store, "positions", code) is None:
            store.execute(
                "INSERT INTO positions (id, department_id, code, title, level,"
                " authority_scope, headcount_baseline, effective_from,"
                " effective_to, created_at, updated_at, is_deleted)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 0)",
                (
                    new_id(),
                    dept_ids["BGD"],
                    code,
                    title,
                    level,
                    encode_json({}),
                    baseline,
                    now,
                    now,
                    now,
                ),
            )

    base_templates = list(DEPT_POSITION_TEMPLATES) + list(
        DEPT_TECHNICAL_TEMPLATES
    )
    for dept_code, _ in DEPARTMENTS:
        dept_templates = list(base_templates)
        if dept_code == "TCKT":
            dept_templates += list(TCKT_EXTRA_TEMPLATES)
        for suffix, title, baseline in dept_templates:
            pos_code = f"DAK-{dept_code}-{suffix}"
            if _get_id(store, "positions", pos_code) is None:
                store.execute(
                    "INSERT INTO positions (id, department_id, code, title,"
                    " level, authority_scope, headcount_baseline,"
                    " effective_from, effective_to, created_at, updated_at,"
                    " is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL,"
                    " ?, ?, 0)",
                    (
                        new_id(),
                        dept_ids[dept_code],
                        pos_code,
                        f"{title} {dept_code}",
                        "manager" if suffix == "TP" else "staff",
                        encode_json({}),
                        baseline,
                        now,
                        now,
                        now,
                    ),
                )

    version_row = store.query_one(
        "SELECT id FROM org_versions WHERE version = ?", (ORG_VERSION,)
    )
    if version_row is None:
        store.execute(
            "INSERT INTO org_versions (id, version, label, status,"
            " effective_from, effective_to, detail, created_at, updated_at,"
            " is_deleted) VALUES (?, ?, ?, 'active', ?, NULL, ?, ?, ?, 0)",
            (
                new_id(),
                ORG_VERSION,
                ORG_VERSION_LABEL,
                now,
                encode_json({"departments": 8}),
                now,
                now,
            ),
        )

    return {
        "companies": store.count("companies"),
        "departments": store.count("departments"),
        "positions": store.count("positions"),
        "org_versions": store.count("org_versions"),
    }
