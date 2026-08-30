"""Unit tests: deterministic secret redaction (spec section 20)."""

from __future__ import annotations

from cloud.app.redaction import redact_secrets


class TestApiKeyPatterns:
    def test_openai_style_key_redacted(self):
        result = redact_secrets("my key is sk-proj-abcdefgh123456789012 ok")
        assert "sk-proj-abcdefgh123456789012" not in result.text
        assert "[REDACTED_API_KEY]" in result.text
        assert result.count >= 1

    def test_github_token_redacted(self):
        token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3"
        result = redact_secrets(f"token {token} leaked")
        assert token not in result.text
        assert "[REDACTED_GITHUB_TOKEN]" in result.text

    def test_aws_key_redacted(self):
        result = redact_secrets("AKIAIOSFODNN7EXAMPLE is secret")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.text
        assert "[REDACTED_AWS_ACCESS_KEY]" in result.text

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = redact_secrets(f"auth {jwt}")
        assert jwt not in result.text
        assert "[REDACTED_JWT]" in result.text

    def test_private_key_block_redacted(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
        )
        result = redact_secrets(pem)
        assert "MIIEowIBAAKCAQEA" not in result.text
        assert "[REDACTED_PRIVATE_KEY]" in result.text

    def test_bearer_header_redacted(self):
        result = redact_secrets("Authorization was Bearer abcdefghijklmnop1234567890")
        assert "abcdefghijklmnop1234567890" not in result.text
        assert "Bearer [REDACTED_TOKEN]" in result.text

    def test_assignment_style_secrets_redacted(self):
        cases = [
            "password=hunter2secret",
            "PASSWORD: hunter2secret",
            "api_key = super-secret-value",
            'client_secret:"very-secret-token"',
        ]
        for text in cases:
            result = redact_secrets(text)
            assert "[REDACTED]" in result.text
            assert result.count >= 1


class TestSafeContent:
    def test_normal_content_untouched(self):
        text = "Vendor A delayed mechanical drawing approval by 21 days. Importance: high."
        result = redact_secrets(text)
        assert result.text == text
        assert result.count == 0

    def test_empty_and_none_like(self):
        assert redact_secrets("").text == ""
        assert redact_secrets("").count == 0

    def test_vietnamese_content_preserved(self):
        text = "Chủ đầu tư yêu cầu phê duyệt bản vẽ cơ điện trong 14 ngày."
        result = redact_secrets(text)
        assert result.text == text
