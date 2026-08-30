"""Unit tests: local redaction parity (spec section 20)."""

from __future__ import annotations

import pytest

from local.redaction import redact_secrets


@pytest.mark.parametrize(
    "raw,marker",
    [
        ("key sk-proj-abcdefgh123456789 here", "[REDACTED_API_KEY]"),
        ("token ghp_" + "x" * 30, "[REDACTED_GITHUB_TOKEN]"),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_ACCESS_KEY]"),
        ("Bearer abcdefghijklmnop1234567890", "Bearer [REDACTED_TOKEN]"),
        ("password=hunter2", "[REDACTED]"),
    ],
)
def test_secrets_redacted(raw, marker):  # type: ignore[no-untyped-def]
    result = redact_secrets(raw)
    assert marker in result.text
    assert result.count >= 1


def test_clean_text_untouched():  # type: ignore[no-untyped-def]
    text = "Vendor drawings must arrive 14 days before procurement."
    result = redact_secrets(text)
    assert result.text == text and result.count == 0
