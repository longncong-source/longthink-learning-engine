#!/usr/bin/env bash
# Second Brain backup (spec section 45). See scripts/backup.ps1 for details.
set -euo pipefail
cd "$(dirname "$0")/.."

OUTPUT_DIR="${1:-backups}"
KEEP_DAYS="${2:-30}"
mkdir -p "$OUTPUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

BACKEND="sqlite"
ENV_FILE="cloud/.env"
[ -f "$ENV_FILE" ] && BACKEND="$(grep -E '^MEMORY_DB_BACKEND=' "$ENV_FILE" | cut -d= -f2 | tr -d '[:space:]')"
BACKEND="${BACKEND:-sqlite}"

if [ "$BACKEND" = "postgres" ]; then
    DB_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2 || true)"
    DB_NAME="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2 || true)"
    DB_USER="${DB_USER:-second_brain}"
    DB_NAME="${DB_NAME:-second_brain}"
    echo "Backing up PostgreSQL ($DB_NAME) via container fsb-db..."
    docker exec fsb-db pg_dump -U "$DB_USER" -d "$DB_NAME" -F c -f /tmp/fsb-backup.dump
    TARGET="$OUTPUT_DIR/second_brain-$STAMP.dump"
    docker cp fsb-db:/tmp/fsb-backup.dump "$TARGET"
    docker exec fsb-db rm /tmp/fsb-backup.dump >/dev/null
else
    DB="data/second_brain.sqlite3"
    [ -f "$DB" ] || { echo "SQLite database not found at $DB" >&2; exit 1; }
    TARGET="$OUTPUT_DIR/second_brain-$STAMP.sqlite3"
    # sqlite3 online-backup API includes WAL contents (a raw copy would not)
    PY=".venv/bin/python"; [ -x "$PY" ] || PY=python3
    FSB_SRC="$PWD/$DB" FSB_DST="$PWD/$TARGET" "$PY" -c \
        "import os, sqlite3; s = sqlite3.connect(os.environ['FSB_SRC']); d = sqlite3.connect(os.environ['FSB_DST']); s.backup(d); d.close(); s.close()"
fi

echo "Backup written: $TARGET"
find "$OUTPUT_DIR" -type f -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/pruned old backup: /'
echo "Done."
