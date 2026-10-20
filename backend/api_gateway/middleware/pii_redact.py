"""PII redaction middleware (Enterprise Hardening Phase 3, Req 6).

Ensures PII never reaches logs, telemetry, or audit detail. The middleware:

- In strict mode (default in non-dev), redacts the request query string before it
  can be logged and stores the redacted form on ``request.state`` for log binding.
- Records that PII redaction ran (``request.state.pii_redacted``).

It does NOT modify primary business data the customer intentionally submits in the
request body (Req 6.3) — only the metadata that flows into logs/telemetry/audit. The
detectors live in ``backend.pii_redactor`` and are reused by the logging filter and
audit-detail construction.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.pii_redactor import redact


def _strict_mode_default() -> bool:
    """Strict mode is on unless explicitly disabled, and off in dev by default."""
    env = os.environ.get("PII_STRICT_MODE")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    # Default: strict everywhere except local dev.
    return os.environ.get("APP_ENV", "dev").lower() != "dev"


class PiiRedactMiddleware(BaseHTTPMiddleware):
    """Redacts PII from request metadata destined for logs/telemetry/audit.

    Args:
        app: The ASGI application.
        strict: When True, the request query string is PII-redacted and exposed on
            ``request.state.redacted_query`` for safe logging. Defaults to env-driven.
    """

    def __init__(self, app, strict: bool | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self._strict = strict if strict is not None else _strict_mode_default()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Mark that PII redaction middleware has executed (middleware-order tests).
        request.state.pii_redacted = True

        if self._strict:
            raw_query = request.url.query or ""
            # Expose a redacted query string for any logging that records the path.
            request.state.redacted_query = redact(raw_query) if raw_query else ""

        return await call_next(request)
