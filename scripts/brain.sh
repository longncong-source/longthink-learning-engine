#!/usr/bin/env bash
# brain CLI wrapper (repo root)
cd "$(dirname "$0")/.."
exec ./.venv/bin/python -m local.brain_cli "$@"
