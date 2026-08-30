"""Client-side secret redaction (spec section 20 - defence BEFORE upload).

Deliberately a standalone copy of the server-side filter: First Brain must be able
to run (and protect secrets) even when deployed independently from the cloud stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED_TOKEN]"),
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
    if not text:
        return RedactionResult(text="", count=0)
    cleaned = text
    total = 0
    for pattern, replacement in _REDACTION_PATTERNS:
        cleaned, n = pattern.subn(replacement, cleaned)
        total += n
    return RedactionResult(text=cleaned, count=total)
