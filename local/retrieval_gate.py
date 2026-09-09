"""First Brain retrieval gate (tini-agent pattern: decide WHETHER to retrieve).

Tini answers "does THIS turn need memory?" with a small model before touching
any store. Here the same contract runs as a deterministic pre-filter: zero
tokens, offline-safe. Fail-open: anything not obviously memory-free retrieves
(a spare search beats a lost memory). A small-model gate may replace or
augment this later; the :class:`GateDecision` contract stays the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MATH_RE = re.compile(r"\d\s*[\+\-\*×x\/÷]\s*\d")
_SMALLTALK_RE = re.compile(
    r"^(hi|hello|hey|yo|thanks|thank you|ok|okay|bye|got it|great|perfect)\b[\s.!?]*$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class GateDecision:
    retrieve: bool
    reason: str
    query: str


def should_retrieve(message: str) -> GateDecision:
    """Return whether this turn needs memory retrieval at all."""
    text = (message or "").strip()
    if not text:
        return GateDecision(False, "empty message", "")
    if len(text) <= 32 and _MATH_RE.search(text):
        return GateDecision(False, "pure math", text)
    if len(text) <= 32 and _SMALLTALK_RE.match(text):
        return GateDecision(False, "small talk", text)
    return GateDecision(True, "fail-open: may reference memory", text)
