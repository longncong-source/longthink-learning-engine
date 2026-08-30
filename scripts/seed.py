"""Seed the Second Brain with the spec section 27 sample knowledge (idempotent).

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\seed.py [--url http://127.0.0.1:8100] [--key dev-local-key]
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed LNG Project memories")
    parser.add_argument("--url", default=None)
    parser.add_argument("--key", default=None)
    args = parser.parse_args()

    from local.config import get_brain_settings
    from local.local_store import LocalStore
    from local.memory_client import SecondBrainClient

    settings = get_brain_settings()
    overrides: dict = {}
    if args.url:
        overrides["second_brain_url"] = args.url
    if args.key:
        overrides["second_brain_api_key"] = args.key
    if overrides:
        settings = settings.model_copy(update=overrides)

    client = SecondBrainClient(settings=settings, store=LocalStore(settings.local_data_dir + "/seed.db"))
    if client.health() is None:
        print("Second Brain unreachable - start the Memory API first.")
        return 2

    project_id = client.ensure_project("LNG Project", description="Long Nhôn LNG terminal project")
    print(f"project: LNG Project ({project_id})")

    seeds = [
        ("Vendor A delayed mechanical drawing approval by 21 days.", "episodic", 0.75),
        ("Engineering document review must start before procurement.", "lesson", 0.70),
        ("We decided to require vendor drawings 14 days before procurement.", "decision", 0.85),
        ("LNG Project uses the FIDIC Silver Book contract model.", "semantic", 0.55),
    ]
    for text, mtype, importance in seeds:
        outcome = client.write_memory(
            title=text[:120],
            content=text,
            type=mtype,
            importance=importance,
            confidence=0.9,
            source="seed-script",
            project_id=project_id,
            allow_cloud=True,
        )
        print(f"[{outcome.status}] ({mtype}) {text[:70]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
