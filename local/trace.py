"""First Brain turn trace (tini-agent pattern: a trace is just "what happened, in order").

Every agent turn appends readable JSON lines to
``<local_data_dir>/traces/<YYYY-MM-DD>.jsonl`` — zero setup, always on, and
best-effort: trace I/O must never break the loop.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


class TurnTracer:
    """One tracer per agent turn. All methods are no-ops when disabled."""

    def __init__(self, trace_dir: str | Path | None = None) -> None:
        self.turn_id = uuid.uuid4().hex[:12]
        self._dir = Path(trace_dir) if trace_dir else None
        self._file: Path | None = None
        if self._dir is not None:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._file = self._dir / f"{time.strftime('%Y-%m-%d')}.jsonl"
            except Exception:
                self._file = None

    @property
    def enabled(self) -> bool:
        return self._file is not None

    def event(self, name: str, **fields) -> None:
        if self._file is None:
            return
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "turn_id": self.turn_id, "event": name}
        record.update(fields)
        try:
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            self._file = None  # one I/O failure disables tracing for this turn
