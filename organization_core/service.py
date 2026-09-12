"""Standalone service entrypoint (Phase 12 deployment).

Exposes ``app`` for uvicorn and ``main()`` for ``python -m`` runs.
DB path / host / port come from the environment (see .env.example).
"""

from __future__ import annotations

import os

from organization_core.api import create_org_app
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


def build_app():
    store = OrganizationStore(
        os.environ.get("ORGANIZATION_CORE_DB", "data/organization.sqlite3"))
    store.init_schema()
    seed_dak(store)
    return create_org_app(store)


app = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "organization_core.service:app",
        host=os.environ.get("ORGANIZATION_CORE_HOST", "127.0.0.1"),
        port=int(os.environ.get("ORGANIZATION_CORE_PORT", "8101")),
    )


if __name__ == "__main__":
    main()
