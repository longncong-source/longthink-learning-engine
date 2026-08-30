"""brain - command line interface for the First Brain (spec sections 28/29).

Usage (from repo root, venv active):
    python -m local.brain_cli doctor
    python -m local.brain_cli memory search "mechanical delay"
    python -m local.brain_cli demo --yes

Or via wrapper: scripts\\brain.ps1 doctor
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # Windows console UTF-8 safety
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass


def _settings():
    from local.config import get_brain_settings

    return get_brain_settings()


def _client(settings=None):  # type: ignore[no-untyped-def]
    from local.memory_client import SecondBrainClient

    return SecondBrainClient(settings or _settings())


def _print_json(data) -> None:  # type: ignore[no-untyped-def]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _resolve_project(client, value: str | None) -> str | None:  # type: ignore[no-untyped-def]
    """Accept a project id OR a case-insensitive project name; None passes through."""
    if not value:
        return None
    try:
        import uuid as _uuid

        _uuid.UUID(value)
        return value
    except ValueError:
        pass
    for project in client.projects():
        if project.get("name", "").lower() == value.lower():
            return str(project["id"])
    raise ValueError(f"Project '{value}' not found (create it with: brain project create {value})")


# --------------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings()
    client = _client(settings)
    health = client.health()
    code, details = client.details()

    from local.llm import llm_online

    print("First Brain")
    print("-" * 40)
    print(f"[{'OK' if llm_online(settings) else '--'}] local LLM ({settings.llm_provider}: {settings.llm_model})")
    pending = client.store.pending_count()
    print(f"[{'--' if pending else 'OK'}] pending cloud writes: {pending}")

    print("\nSecond Brain")
    print("-" * 40)
    if health:
        print("[OK] API reachable at", settings.second_brain_url)
        if code == 200 and details:
            storage = details.get("storage", {})
            counts = storage.get("counts", {})
            emb = details.get("embeddings", {})
            print(f"[OK] auth valid | backend={storage.get('backend')} | memories={counts.get('memories')}")
            print(f"     embeddings: {emb.get('provider')}/{emb.get('model')} dim={emb.get('dimension')}")
        elif code in (401, 403):
            print("[!!] auth FAILED - check SECOND_BRAIN_API_KEY vs MEMORY_API_KEYS")
            return 1
    else:
        print("[!!] API unreachable - start with:")
        print("     .\\.venv\\Scripts\\python.exe -m uvicorn cloud.app.main:app --port 8100")
        return 1
    return 0


# ---------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings()
    checks: list[tuple[str, bool | None, str]] = []

    # --- First Brain ---
    ok_python = sys.version_info >= (3, 10)
    checks.append(("local runtime (python>=3.10)", ok_python, sys.version.split()[0]))

    try:
        import httpx  # noqa: F401
        import pydantic_settings  # noqa: F401

        deps_ok = True
        dep_detail = "httpx + pydantic-settings importable"
    except ImportError as exc:  # pragma: no cover
        deps_ok, dep_detail = False, str(exc)
    checks.append(("local dependencies", deps_ok, dep_detail))

    result = None
    try:
        from local.redaction import redact_secrets

        probe = redact_secrets("sk-proj-abcdefghijklmnop1234")
        result = probe.count > 0 and "[REDACTED_API_KEY]" in probe.text
    except Exception as exc:
        result = False
        dep_detail = str(exc)
    checks.append(("secret filter active", bool(result), "deterministic regex filter self-test"))

    store_ok = True
    store_detail = ""
    try:
        from local.local_store import LocalStore

        probe_store = LocalStore(Path(settings.local_data_dir) / "doctor-probe.db")
        probe_store.add_note("probe", "doctor")
        probe_store.close()
        Path(settings.local_data_dir, "doctor-probe.db").unlink(missing_ok=True)
        store_detail = f"writable ({settings.local_data_dir})"
    except Exception as exc:
        store_ok, store_detail = False, str(exc)
    checks.append(("local storage", store_ok, store_detail))

    docker_detail = "not installed"
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode == 0:
            docker_detail = f"daemon {proc.stdout.strip()}"
        else:
            docker_detail = (proc.stderr or "daemon unreachable").strip()[:80]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    checks.append(
        ("docker (PostgreSQL/pgvector stack)", None if not args.quick else True,
         f"{docker_detail} - advisory only, SQLite fallback keeps the loop working"),
    )

    from local.llm import llm_online

    llm_up = llm_online(settings)
    checks.append(("LLM server reachable", None,
                   f"{settings.llm_provider}:{settings.resolved_llm_base_url} -> "
                   + ("online" if llm_up else "offline (deterministic fallback active)")))

    # --- Second Brain ---
    client = _client(settings)
    health = client.health()
    checks.append(("Memory API reachable", health is not None,
                   settings.second_brain_url if health is None else "GET /health -> 200"))

    code, details = (None, None)
    if health:
        code, details = client.details()
    auth_ok = code == 200
    auth_detail = {
        None: "API unreachable",
        200: "X-API-Key accepted",
        401: "key rejected - mismatch SECOND_BRAIN_API_KEY / MEMORY_API_KEYS",
        403: "forbidden",
    }.get(code, f"HTTP {code}")
    checks.append(("authentication", auth_ok, str(auth_detail)))

    backend_detail = "-"
    if details:
        storage = details.get("storage", {})
        emb = details.get("embeddings", {})
        backend_detail = (
            f"{storage.get('backend')} reachable={storage.get('reachable')} | "
            f"embeddings={emb.get('provider')} dim={emb.get('dimension')}"
        )
    checks.append(("database + embeddings configured", bool(details), backend_detail))

    env_local = Path("local/.env")
    env_cloud = Path("cloud/.env")
    env_present = env_local.exists() or env_cloud.exists()
    checks.append((".env files present", None if not env_present else True,
                   "local/.env and/or cloud/.env found"
                   if env_present else "not found yet - defaults are used (copy the .env.example files)"))

    gitignore_ok = False
    gi = REPO_ROOT / ".gitignore"
    if gi.exists():
        text = gi.read_text(encoding="utf-8", errors="ignore")
        gitignore_ok = ".env" in text
    checks.append((".env ignored by git", gitignore_ok, str(gi)))

    pending = client.store.pending_count()
    checks.append(("pending write queue empty", None if pending else True,
                   f"{pending} item(s) - run 'brain sync'"))

    # --- report ---
    if args.json:
        _print_json([
            {"check": name, "ok": ok, "detail": detail} for name, ok, detail in checks
        ])
    else:
        print("First Brain")
        print("-" * 60)
        for name, ok, detail in checks[:6]:
            marker = {True: "[OK]", False: "[FAIL]", None: "[--]"}[ok]
            print(f"{marker} {name}\n      {detail}")
        print("Second Brain")
        print("-" * 60)
        for name, ok, detail in checks[6:]:
            marker = {True: "[OK]", False: "[FAIL]", None: "[--]"}[ok]
            print(f"{marker} {name}\n      {detail}")

    critical_failures = [name for name, ok, _ in checks if ok is False]
    if critical_failures:
        print(f"\nDoctor result: FAIL ({len(critical_failures)} critical)")
        return 1
    print("\nDoctor result: PASS")
    return 0


# ---------------------------------------------------------------------- memory
def cmd_memory_search(args: argparse.Namespace) -> int:
    client = _client()
    data = client.search(
        args.query,
        project_id=_resolve_project(client, args.project),
        top_k=args.top_k,
        mtype=args.type,
        min_importance=args.min_importance,
    )
    results = data.get("results", [])
    if args.json:
        _print_json(data)
        return 0
    cached = " (cache HIT)" if data.get("_cache") == "hit" else ""
    print(f"query: {args.query!r} -> {len(results)} result(s){cached}")
    for i, r in enumerate(results, start=1):
        print(f"\n{i}. [{r.get('type')}] score={r.get('score')} {r.get('title')}")
        content = (r.get("content") or "").strip()
        print(f"   {content[:220]}{'...' if len(content) > 220 else ''}")
        scores = r.get("scores", {})
        print(f"   semantic={scores.get('semantic')} keyword={scores.get('keyword')} "
              f"importance={scores.get('importance')} recency={scores.get('recency')}")
    return 0


def cmd_memory_add(args: argparse.Namespace) -> int:
    client = _client()
    outcome = client.write_memory(
        title=args.title,
        content=args.content,
        type=args.type,
        importance=args.importance,
        confidence=args.confidence,
        source=args.source or "cli",
        project_id=_resolve_project(client, args.project),
        allow_cloud=not args.no_cloud,
    )
    print(f"status={outcome.status}"
          + (f" id={outcome.memory_id}" if outcome.memory_id else "")
          + (" deduplicated" if outcome.deduplicated else "")
          + (f" redactions={outcome.redaction_count}" if outcome.redaction_count else ""))
    if outcome.detail:
        print(outcome.detail)
    return 0 if outcome.status in {"stored", "queued"} else 1


def cmd_memory_list(args: argparse.Namespace) -> int:
    client = _client()
    rows = client.list_memories(limit=args.limit, project_id=args.project, mtype=args.type)
    if args.json:
        _print_json(rows)
        return 0
    print(f"{len(rows)} memory(ies)")
    for r in rows:
        print(f"- [{r.get('type')}] imp={r.get('importance')} {r.get('title')}  (id={r.get('id')})")
    return 0


def cmd_memory_delete(args: argparse.Namespace) -> int:
    client = _client()
    deleted = client.delete_memory(args.id)
    print("deleted" if deleted else "not found")
    return 0 if deleted else 1


# --------------------------------------------------------------------- project
def cmd_project_list(args: argparse.Namespace) -> int:
    client = _client()
    projects = client.projects()
    if args.json:
        _print_json(projects)
        return 0
    for p in projects:
        print(f"- {p.get('name')}  (id={p.get('id')}, status={p.get('status')})")
    print(f"total: {len(projects)}")
    return 0


def cmd_project_create(args: argparse.Namespace) -> int:
    client = _client()
    project_id = client.ensure_project(args.name, description=args.description or "")
    print(f"project ready: {args.name} (id={project_id})")
    return 0


# ------------------------------------------------------------------------ sync
def cmd_sync(args: argparse.Namespace) -> int:
    client = _client()
    report = client.sync(max_items=args.max)
    print(f"sent={report.sent} permanent_failures={report.permanent_failures} remaining={report.remaining}")
    for err in report.errors:
        print(f"  ! {err}")
    return 0 if report.remaining == 0 else 1


# ------------------------------------------------------------------------ demo
def cmd_demo(args: argparse.Namespace) -> int:
    from local.config import get_brain_settings
    from local.demo import run_demo
    from local.llm import get_chat_llm

    settings = get_brain_settings()
    return run_demo(
        client=_client(settings),
        llm=get_chat_llm(settings),
        auto_yes=not args.ask,
        offline_ok=args.offline_ok,
        decision_text=args.decision,
    )


# ------------------------------------------------------------------------ docs
def cmd_doc_upload(args: argparse.Namespace) -> int:
    client = _client()
    result = client.upload_document(
        args.path,
        project_id=_resolve_project(client, args.project),
        title=args.title,
        source=args.source,
    )
    doc = result["document"]
    print(f"indexed: {result['chunks_indexed']} chunk(s) from {doc['filename']}")
    print(f"document id: {doc['id']}  (mime={doc['mime_type']}, pages={doc.get('metadata', {}).get('pages')})")
    return 0


def cmd_doc_list(args: argparse.Namespace) -> int:
    client = _client()
    rows = client.list_documents(limit=args.limit, project_id=_resolve_project(client, args.project))
    if args.json:
        _print_json(rows)
        return 0
    print(f"{len(rows)} document(s)")
    for d in rows:
        print(f"- {d.get('filename')}  (id={d.get('id')}, mime={d.get('mime_type')})")
    return 0


def cmd_doc_delete(args: argparse.Namespace) -> int:
    client = _client()
    deleted = client.delete_document(args.id)
    print("deleted (chunks + mirrored memories removed)" if deleted else "not found")
    return 0 if deleted else 1


# --------------------------------------------------------------------- obsidian
def cmd_obsidian_scan(args: argparse.Namespace) -> int:
    """Scan Obsidian vault and sync eligible notes to brain."""
    settings = _settings()
    if not settings.obsidian_vault_path:
        print("error: OBSIDIAN_VAULT_PATH not configured in local/.env")
        return 1

    from local.obsidian_service import scan_vault
    client = _client(settings)

    result = scan_vault(
        settings.obsidian_vault_path,
        project_id=_resolve_project(client, args.project),
        default_type=args.default_type,
        settings=settings,
        client=client,
    )

    if args.json:
        _print_json(result)
        return 0

    print(f"Obsidian Vault Sync: {settings.obsidian_vault_path}")
    print(f"  Total files: {result['total_files']}")
    print(f"  Synced to cloud: {result['synced']}")
    print(f"  Local only: {result['local_only']}")
    print(f"  Queued: {result['queued']}")
    print(f"  Skipped: {result['skipped']}")
    print(f"  Errors: {result['errors']}")

    if result["items"]:
        print("\nDetails:")
        for item in result["items"]:
            status_marker = {
                "indexed": "[OK]",
                "local_only": "[LOCAL]",
                "queued": "[QUEUE]",
                "skipped": "[--]",
                "error": "[ERR]",
            }.get(item["status"], "[?]")
            print(f"  {status_marker} {item['file']} -> {item['status']}"
                  + (f" (id={item.get('memory_id')})" if item.get("memory_id") else "")
                  + (f" {item.get('error','')}" if item.get("error") else ""))

    return 0 if result["errors"] == 0 else 1


def cmd_obsidian_sync(args: argparse.Namespace) -> int:
    """Sync a single Obsidian note to brain."""
    settings = _settings()
    if not settings.obsidian_vault_path:
        print("error: OBSIDIAN_VAULT_PATH not configured in local/.env")
        return 1

    from local.obsidian_service import sync_note
    client = _client(settings)

    # Read the note file
    note_path = Path(settings.obsidian_vault_path) / args.file
    if not note_path.exists():
        print(f"error: note not found: {note_path}")
        return 1

    content = note_path.read_text(encoding="utf-8")

    result = sync_note(
        args.file,
        content,
        project_id=_resolve_project(client, args.project),
        default_type=args.default_type,
        settings=settings,
        client=client,
    )

    if args.json:
        _print_json(result)
        return 0

    print(f"Sync result: {result['status']}"
          + (f" id={result.get('memory_id')}" if result.get("memory_id") else "")
          + (f" redactions={result.get('redaction_count', 0)}" if result.get("redaction_count") else "")
          + (f" reason={result.get('reason')}" if result.get("reason") else "")
          + (f" error={result.get('error')}" if result.get("error") else ""))

    return 0 if result["status"] != "error" else 1


def cmd_obsidian_export(args: argparse.Namespace) -> int:
    """Export a memory from First Brain to Obsidian."""
    settings = _settings()
    if not settings.obsidian_vault_path:
        print("error: OBSIDIAN_VAULT_PATH not configured in local/.env")
        return 1

    from local.obsidian_service import export_memory_to_obsidian
    client = _client(settings)

    # Get memory from Second Brain
    status, memory = client.get_memory(args.memory_id)
    if status != 200 or not memory:
        print(f"error: memory not found: {args.memory_id}")
        return 1

    result = export_memory_to_obsidian(
        memory,
        vault_path=settings.obsidian_vault_path,
        folder=args.folder,
        settings=settings,
    )

    if args.json:
        _print_json(result)
        return 0

    print(f"Export result: {result['status']}"
          + (f" file={result.get('file')}" if result.get("file") else "")
          + (f" error={result.get('error')}" if result.get("error") else ""))

    return 0 if result["status"] != "error" else 1


# ----------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="First Brain CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="quick status overview")
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser("doctor", help="full environment diagnostics")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("--quick", action="store_true", help="skip slow external probes")
    p_doctor.set_defaults(func=cmd_doctor)

    p_demo = sub.add_parser("demo", help="run the MVP end-to-end demo (spec section 27)")
    p_demo.add_argument("--yes", action="store_true", help="auto-approve human-in-the-loop prompts (default)")
    p_demo.add_argument("--ask", action="store_true", help="interactive confirmation")
    p_demo.add_argument("--offline-ok", action="store_true")
    p_demo.add_argument("--decision", default=None)
    p_demo.set_defaults(func=cmd_demo)

    p_sync = sub.add_parser("sync", help="flush queued writes to the Second Brain")
    p_sync.add_argument("--max", type=int, default=None)
    p_sync.set_defaults(func=cmd_sync)

    mem = sub.add_parser("memory", help="memory operations")
    mem_sub = mem.add_subparsers(dest="memory_command", required=True)

    p_search = mem_sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--project", default=None)
    p_search.add_argument("--top-k", type=int, default=None)
    p_search.add_argument("--type", default=None)
    p_search.add_argument("--min-importance", type=float, default=None)
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_memory_search)

    p_add = mem_sub.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--type", default="semantic")
    p_add.add_argument("--importance", type=float, default=0.5)
    p_add.add_argument("--confidence", type=float, default=0.8)
    p_add.add_argument("--source", default=None)
    p_add.add_argument("--project", default=None)
    p_add.add_argument("--no-cloud", action="store_true", help="force local-only this time")
    p_add.set_defaults(func=cmd_memory_add)

    p_list = mem_sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--project", default=None)
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_memory_list)

    p_del = mem_sub.add_parser("delete")
    p_del.add_argument("id")
    p_del.set_defaults(func=cmd_memory_delete)

    proj = sub.add_parser("project", help="project operations")
    proj_sub = proj.add_subparsers(dest="project_command", required=True)

    p_plist = proj_sub.add_parser("list")
    p_plist.add_argument("--json", action="store_true")
    p_plist.set_defaults(func=cmd_project_list)

    p_pcreate = proj_sub.add_parser("create")
    p_pcreate.add_argument("name")
    p_pcreate.add_argument("--description", default="")
    p_pcreate.set_defaults(func=cmd_project_create)

    doc = sub.add_parser("doc", help="document RAG operations (upload/list/delete)")
    doc_sub = doc.add_subparsers(dest="doc_command", required=True)

    p_dupload = doc_sub.add_parser("upload", help="ingest PDF/DOCX/TXT/MD into the Second Brain")
    p_dupload.add_argument("path")
    p_dupload.add_argument("--project", default=None, help="project id or name")
    p_dupload.add_argument("--title", default=None)
    p_dupload.add_argument("--source", default=None)
    p_dupload.set_defaults(func=cmd_doc_upload)

    p_dlist = doc_sub.add_parser("list")
    p_dlist.add_argument("--limit", type=int, default=50)
    p_dlist.add_argument("--project", default=None)
    p_dlist.add_argument("--json", action="store_true")
    p_dlist.set_defaults(func=cmd_doc_list)

    p_ddel = doc_sub.add_parser("delete")
    p_ddel.add_argument("id")
    p_ddel.set_defaults(func=cmd_doc_delete)

    obs = sub.add_parser("obsidian", help="Obsidian vault operations")
    obs_sub = obs.add_subparsers(dest="obsidian_command", required=True)

    p_oscan = obs_sub.add_parser("scan", help="scan vault and sync all eligible notes")
    p_oscan.add_argument("--project", default=None, help="project id or name")
    p_oscan.add_argument("--default-type", default="semantic", help="default memory type")
    p_oscan.add_argument("--json", action="store_true")
    p_oscan.set_defaults(func=cmd_obsidian_scan)

    p_osync = obs_sub.add_parser("sync", help="sync a single note by relative path")
    p_osync.add_argument("file", help="relative path in vault (e.g., '04_Lessons/lesson.md')")
    p_osync.add_argument("--project", default=None, help="project id or name")
    p_osync.add_argument("--default-type", default="semantic", help="default memory type")
    p_osync.add_argument("--json", action="store_true")
    p_osync.set_defaults(func=cmd_obsidian_sync)

    p_oexport = obs_sub.add_parser("export", help="export a memory to Obsidian")
    p_oexport.add_argument("memory_id", help="memory ID to export")
    p_oexport.add_argument("--folder", default="07_ai_memory", help="vault subfolder")
    p_oexport.add_argument("--json", action="store_true")
    p_oexport.set_defaults(func=cmd_obsidian_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
