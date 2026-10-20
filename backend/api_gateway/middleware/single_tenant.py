"""Single-tenant enforcement middleware (Enterprise Hardening Req 1.2).

In dedicated_vpc / customer_managed deployments the system serves exactly one tenant.
Any request whose resolved ``tenant_id`` differs from the configured
``dedicated_tenant_id`` is rejected with the uniform ``resource_not_found`` response —
the same shape used for cross-tenant access — so no existence information leaks.

Runs after auth (which sets ``request.state.tenant_id``). In pooled mode it is a
pass-through and need not be installed.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Endpoints that are tenant-agnostic and must remain reachable.
_EXEMPT_PATHS: set[str] = {
    "/health",
    "/health/live",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/openapi.json",
}


class SingleTenantMiddleware(BaseHTTPMiddleware):
    """Rejects foreign-tenant requests in single-tenant deployment modes."""

    def __init__(self, app, dedicated_tenant_id: str) -> None:  # noqa: ANN001
        super().__init__(app)
        if not dedicated_tenant_id:
            raise ValueError("dedicated_tenant_id is required for single-tenant mode")
        self._dedicated_tenant_id = dedicated_tenant_id

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        # Only enforce once a tenant has been resolved by auth. Unauthenticated
        # requests are handled by the auth layer.
        if tenant_id is not None and tenant_id != self._dedicated_tenant_id:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "resource_not_found",
                        "message": "The requested resource was not found",
                    }
                },
            )

        return await call_next(request)
