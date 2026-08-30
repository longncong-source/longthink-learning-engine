"""Deterministic secret redaction applied BEFORE anything is stored (spec section 20).

Never trust the LLM alone for secret filtering - these are regex-based,
runnable without any model, and applied both server-side and client-side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (compiled pattern, replacement)
REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI-style keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # GitHub tokens
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    # AWS access key ids
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    # JWTs
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
        "[REDACTED_JWT]",
    ),
    # PEM private key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Authorization headers
    (re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED_TOKEN]"),
    # key=value / password: value style assignments
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
            r"(\s*[:=]\s*)([\"']?)[^\s\"'&,;]+"
        ),
        r"\1\2\3[REDACTED]",
    ),
]


@dataclass(slots=True)
class RedactionResult:
    text: str
    count: int


def redact_secrets(text: str) -> RedactionResult:
    """Return redacted copy of *text* plus number of redactions applied."""
    if not text:
        return RedactionResult(text="", count=0)
    cleaned = text
    total = 0
    for pattern, replacement in REDACTION_PATTERNS:
        cleaned, n = pattern.subn(replacement, cleaned)
        total += n
    return RedactionResult(text=cleaned, count=total)
