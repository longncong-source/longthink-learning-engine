"""Seed org projects for multi-assistant deployment (6 phong + BGD) — idempotent.

Creates the 8 shared projects (find-by-name, never duplicates) directly in the
configured storage backend, so no running API is needed:
    .\\.venv\\Scripts\\python.exe scripts\\seed_org.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_org.py --with-acl-skeleton

--with-acl-skeleton prints fresh random API keys + an ORG_ACL_JSON skeleton.
Paste the keys into cloud/.env MEMORY_API_KEYS and the JSON into ORG_ACL_JSON.
Keys are printed ONLY to stdout (never written to disk by this script).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORG_PROJECTS: list[tuple[str, str, dict]] = [
    ("congty_chung", "Công ty chung — tri thức đã duyệt, ai cũng đọc", {"phong": "congty", "loai": "chung"}),
    ("bgd_rieng", "BGĐ riêng — chỉ Ban Giám Đốc", {"phong": "bgd", "loai": "rieng"}),
    ("phong_tchc_chung", "TCHC chung — Tổ chức Hành chính", {"phong": "phong_tchc_chung", "loai": "chung"}),
    ("phong_tckt_chung", "TCKT chung — Tài chính Kế toán", {"phong": "phong_tckt_chung", "loai": "chung"}),
    ("phong_kthd_chung", "KTHD chung — Kinh tế Hợp đồng", {"phong": "phong_kthd_chung", "loai": "chung"}),
    ("phong_ptda_chung", "PTDA chung — Phát triển Dự án", {"phong": "phong_ptda_chung", "loai": "chung"}),
    ("phong_tkcn_chung", "TKCN chung — Thiết kế Công nghệ", {"phong": "phong_tkcn_chung", "loai": "chung"}),
    ("phong_ktgs_chung", "KTGS chung — Kỹ thuật Giám sát", {"phong": "phong_ktgs_chung", "loai": "chung"}),
]

ACL_SKELETON = [
    {"user": "bgd_giamdoc", "phong": "bgd", "role": "bgd", "data_policy": "cloud_allowed"},
    {"user": "admin_it", "phong": "admin", "role": "admin", "data_policy": "local_only"},
    {"user": "tckt_truongphong", "phong": "phong_tckt_chung", "role": "truong_phong",
     "data_policy": "local_only", "reports": ["tckt_nhanvien"], "rate_limit": 120},
    {"user": "tckt_nhanvien", "phong": "phong_tckt_chung", "role": "nhan_vien", "data_policy": "local_only"},
]


def seed_projects(backend: str = "sqlite", sqlite_path: str | None = None) -> dict[str, str]:
    from cloud.app.config import get_settings
    from cloud.app.db import ProjectRecord, build_repository

    settings = get_settings()
    if backend:
        settings = settings.model_copy(update={"memory_db_backend": backend})
    if sqlite_path:
        settings = settings.model_copy(update={"sqlite_path": sqlite_path})
    repo = build_repository(settings)
    repo.init_schema()
    ids: dict[str, str] = {}
    for name, desc, meta in ORG_PROJECTS:
        existing = repo.find_project_by_name(name)
        if existing is not None:
            ids[name] = str(existing.id)
            print(f"[exists] {name} ({existing.id})")
            continue
        created = repo.create_project(ProjectRecord(name=name, description=desc, metadata=dict(meta)))
        ids[name] = str(created.id)
        print(f"[created] {name} ({created.id})")
    close = getattr(repo, "close", None)
    if callable(close):
        close()
    return ids


def print_acl_skeleton() -> None:
    entries = []
    keys: list[str] = []
    for item in ACL_SKELETON:
        key = "lt-" + secrets.token_urlsafe(24)
        keys.append(key)
        entries.append({**item, "key": key})
    print("\n--- MEMORY_API_KEYS (append to cloud/.env) ---")
    print(",".join(keys))
    print("\n--- ORG_ACL_JSON (single line, cloud/.env) ---")
    print(json.dumps(entries, ensure_ascii=False))
    print("\nOnboard thêm nhân viên: copy 1 entry, đổi user/phong/role, gen key mới,")
    print("tạo project cá nhân: brain project create nv_<ten>  (BGĐ/Admin chạy)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed 8 org projects (idempotent)")
    parser.add_argument("--with-acl-skeleton", action="store_true")
    parser.add_argument("--backend", default="sqlite", choices=["sqlite", "postgres"],
                        help="storage backend to seed (default sqlite for laptop)")
    parser.add_argument("--sqlite-path", default=None)
    args = parser.parse_args()

    seed_projects(backend=args.backend, sqlite_path=args.sqlite_path)
    if args.with_acl_skeleton:
        print_acl_skeleton()
    else:
        print("\nTip: --with-acl-skeleton để sinh keys + ORG_ACL_JSON mẫu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
