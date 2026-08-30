#!/usr/bin/env bash
# First Brain + Second Brain - one-time setup for macOS/Linux.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4 Python venv =="
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip

echo "== 2/4 Dependencies =="
./.venv/bin/python -m pip install \
    -r cloud/requirements.txt \
    -r local/requirements.txt \
    -r requirements-dev.txt

echo "== 3/4 Environment files =="
[ -f cloud/.env ] || cp cloud/.env.example cloud/.env
[ -f local/.env ] || cp local/.env.example local/.env

echo "== 4/4 Docker stack (optional) =="
if command -v docker >/dev/null 2>&1; then
    docker compose -f docker-compose.brain.yml up -d --build
else
    echo "Docker not found - SQLite fallback will be used."
fi

./.venv/bin/python -m pytest cloud/tests local/tests -q
./.venv/bin/python -m local.brain_cli doctor --quick
echo "Done. Start API: ./.venv/bin/python -m uvicorn cloud.app.main:app --port 8100"
