"""FastAPI RBAC dependency (Enterprise Hardening Phase 6).

Provides ``requires(permission)`` to gate a route on a permission. The dependency
reads the unified :class:`Principal` placed on ``request.state`` by the auth
middleware and raises :class:`AuthorizationError` (mapped to 403) when the principal
lacks the permission.
"""

from __future__ import annotations

from fastapi import Request

from backend.auth.rbac import Permission, require_permission
from backend.providers.interfaces import Principal


def get_principal(request: Request) -> Principal | None:
    """Return the authenticated Principal from request.state, if any."""
    return getattr(request.state, "principal", None)


def requires(permission: Permission):
    """Build a FastAPI dependency that enforces ``permission`` for the route."""

    async def _dependency(request: Request) -> Principal | None:
        principal = get_principal(request)
        require_permission(principal, permission)
        return principal

    return _dependency
