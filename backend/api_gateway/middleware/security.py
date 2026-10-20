"""Security middleware: HTTPS enforcement and security headers (Phase 2).

Implements:
- HTTPS-only guard for API routes in production, honoring the ``X-Forwarded-Proto``
  header set by the load balancer / TLS terminator (Req 3.1).
- Standard security response headers: HSTS, CSP, X-Frame-Options,
  X-Content-Type-Options, Referrer-Policy (Req 14.7).

These are pure additions to the response and a cheap pre-routing check; they do not
alter request bodies.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Endpoints exempt from HTTPS enforcement (local health/doc checks).
_HTTPS_EXEMPT_PATHS: frozenset[str] = frozenset(
    {"/health", "/health/live", "/health/ready"}
)

# Conservative security headers suitable for an API + docs UI.
_DEFAULT_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _is_https(request: Request) -> bool:
    """Determine whether the original client request used HTTPS.

    Honors ``X-Forwarded-Proto`` (set by the ALB / TLS terminator); falls back to the
    request URL scheme for direct connections.
    """
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        # May be a comma-separated list (proxies); the left-most is the client.
        return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforces HTTPS (in prod) and attaches security headers to every response.

    Args:
        app: The ASGI application.
        https_only: When True, non-HTTPS API requests are rejected with 400.
            Typically enabled in production (APP_ENV != dev).
        hsts: When False, the Strict-Transport-Security header is omitted (useful for
            plain-HTTP local runs).
    """

    def __init__(self, app, *, https_only: bool = False, hsts: bool = True) -> None:  # noqa: ANN001
        super().__init__(app)
        self._https_only = https_only
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            self._https_only
            and request.url.path not in _HTTPS_EXEMPT_PATHS
            and not _is_https(request)
        ):
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "https_required",
                        "message": "This endpoint requires a secure (HTTPS) connection.",
                    }
                },
            )

        response = await call_next(request)

        for header, value in _DEFAULT_SECURITY_HEADERS.items():
            if header == "Strict-Transport-Security" and not self._hsts:
                continue
            response.headers.setdefault(header, value)

        return response
