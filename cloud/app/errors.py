"""Domain errors mapped to meaningful HTTP responses (no hidden failures)."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(DomainError):
    status_code = 401
    code = "unauthorized"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class UpstreamUnavailableError(DomainError):
    status_code = 503
    code = "upstream_unavailable"


class DependencyMissingError(DomainError):
    status_code = 503
    code = "dependency_missing"


class UnsupportedMediaTypeError(DomainError):
    status_code = 415
    code = "unsupported_media_type"


class PayloadTooLargeError(DomainError):
    status_code = 413
    code = "payload_too_large"


class RepositoryError(DomainError):
    status_code = 503
    code = "storage_unavailable"


class RateLimitError(DomainError):
    status_code = 429
    code = "rate_limited"
