"""Auth middleware — dual-plane authentication (API key + human SSO).

Per R13.1, no business handler is invoked before a tenant_id is resolved. This
middleware supports two authentication planes (Phase 5, Req 4):

- **Machine plane** (default): Bearer API key validated by AuthService.
- **Human plane** (SSO): an OIDC token presented via the ``X-SSO-Token`` header (or
  an ``sso_token`` cookie) validated by the configured IdentityProvider.

Both planes converge on a unified ``Principal`` placed on ``request.state.principal``;
``request.state.tenant_id`` / ``api_key_id`` remain set for backward compatibility.

Skips auth for health/docs endpoints.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.providers.interfaces import Principal

if TYPE_CHECKING:
    from backend.auth.service import AuthService
    from backend.providers.interfaces import IdentityProvider


def _machine_roles() -> tuple[str, ...]:
    """Roles granted to API-key (machine) clients.

    Defaults to ('service',). Overridable via MACHINE_API_ROLES (comma-separated)
    for local exploration of admin/auditor surfaces without an SSO token, e.g.
    MACHINE_API_ROLES=org_admin,auditor. Do NOT set this in production.
    """
    raw = os.environ.get("MACHINE_API_ROLES", "").strip()
    if not raw:
        return ("service",)
    roles = tuple(r.strip() for r in raw.split(",") if r.strip())
    return roles or ("service",)

# Paths that skip authentication
_PUBLIC_PATHS: set[str] = {
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/v1/openapi.json",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticates requests via API key or human SSO, unifying to a Principal.

    Args:
        app: ASGI application.
        auth_service: machine-plane API-key authenticator.
        identity_provider: optional human-plane SSO validator (OIDC/SAML).
        sso_required: when True, the machine (API key) plane is disabled and only
            SSO is accepted (per-tenant "SSO only / no password fallback", Req 4.5).
    """

    def __init__(
        self,
        app,  # noqa: ANN001
        auth_service: AuthService,
        identity_provider: IdentityProvider | None = None,
        sso_required: bool = False,
    ) -> None:
        super().__init__(app)
        self._auth_service = auth_service
        self._identity_provider = identity_provider
        self._sso_required = sso_required

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "")

        # --- Human plane: SSO token (preferred when present) ---
        sso_token = request.headers.get("x-sso-token") or request.cookies.get("sso_token")
        if sso_token and self._identity_provider is not None:
            from backend.providers.interfaces import IdentityError

            try:
                principal = await self._identity_provider.verify_assertion(sso_token)
            except IdentityError as e:
                await self._emit_sso_failure(request_id, request.url.path)
                return self._unauthorized("invalid_sso_token", str(e))

            self._bind_principal(request, principal)
            return await call_next(request)

        # --- Machine plane: API key (unless SSO is required for this tenant) ---
        if self._sso_required:
            return self._unauthorized(
                "sso_required", "This tenant requires SSO authentication."
            )

        headers = {k.lower(): v for k, v in request.headers.items()}
        result = await self._auth_service.authenticate(
            headers,
            request_id=request_id,
            resource=request.url.path,
        )

        from backend.auth.service import AuthError

        if isinstance(result, AuthError):
            return self._unauthorized(result.code, result.message)

        request.state.tenant_id = result.tenant_id
        request.state.api_key_id = result.api_key_id
        request.state.principal = Principal(
            tenant_id=result.tenant_id,
            subject=result.api_key_id,
            roles=_machine_roles(),
            auth_kind="machine",
        )

        return await call_next(request)

    def _bind_principal(self, request: Request, principal: Principal) -> None:
        request.state.principal = principal
        request.state.tenant_id = principal.tenant_id
        request.state.api_key_id = principal.subject

    def _unauthorized(self, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": code, "message": message}},
        )

    async def _emit_sso_failure(self, request_id: str, resource: str) -> None:
        """Emit an auth_failure audit event for an invalid SSO assertion (Req 4.7)."""
        emitter = getattr(self._auth_service, "_audit_emitter", None)
        if emitter is None:
            return
        try:
            await emitter.emit(
                action="auth_failure",
                tenant_id=None,
                actor="anonymous",
                resource=resource,
                request_id=request_id or "x" * 16,
                detail={"error_code": "invalid_sso_token", "plane": "sso"},
            )
        except Exception:  # noqa: BLE001 - audit failure must not break the 401 path
            pass
