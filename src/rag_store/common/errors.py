"""Application errors mapped to HTTP responses by the API layer."""

from __future__ import annotations


class RagStoreError(Exception):
    code = "error"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code

    def to_dict(self) -> dict:
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = self.details
        return body


class Unauthorized(RagStoreError):
    code = "unauthorized"
    status_code = 401


class Forbidden(RagStoreError):
    code = "forbidden"
    status_code = 403


class NotFound(RagStoreError):
    code = "not_found"
    status_code = 404


class Conflict(RagStoreError):
    code = "conflict"
    status_code = 409


class PayloadTooLarge(RagStoreError):
    code = "payload_too_large"
    status_code = 413


class ValidationFailed(RagStoreError):
    code = "validation_error"
    status_code = 422


class RateLimited(RagStoreError):
    code = "rate_limited"
    status_code = 429


class QuotaExceeded(RagStoreError):
    code = "quota_exceeded"
    status_code = 429


class Unavailable(RagStoreError):
    code = "unavailable"
    status_code = 503


class LeaseLost(RagStoreError):
    code = "lease_lost"
    status_code = 409


class ConfigurationError(RagStoreError):
    code = "configuration_error"
    status_code = 500
