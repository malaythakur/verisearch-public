"""Role-based access control (Enterprise Hardening Phase 6, Req 4.2-4.4).

Layers RBAC on top of tenant isolation. A request's :class:`Principal` (set by the
auth middleware from either the SSO or API-key plane) carries roles; this module maps
roles to permissions and enforces them at the route boundary.

Roles (Req 4.2):
- ``org_admin``  — full administrative control of the tenant.
- ``analyst``    — day-to-day work: search, answer, index, research, pipelines.
- ``auditor``    — read-only access to the audit log; NO data mutation (Req 4.4).
- ``read_only``  — read-only access to search/answer/contents.
- ``service``    — machine (API-key) clients; full data-plane, no admin.

UI gating is convenience; the server is the source of truth (Req 13.2 / design).
"""

from __future__ import annotations

from enum import Enum

from backend.providers.interfaces import Principal


class Permission(str, Enum):
    """Discrete permissions checked by routes."""

    # Data plane
    SEARCH = "search"
    ANSWER = "answer"
    CONTENTS = "contents"
    INDEX = "index"
    RESEARCH = "research"
    PIPELINE_READ = "pipeline:read"
    PIPELINE_WRITE = "pipeline:write"
    SESSION_WRITE = "session:write"
    # Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    # Admin
    ORG_MANAGE = "org:manage"
    APIKEY_MANAGE = "apikey:manage"
    TENANT_ERASURE = "tenant:erasure"


# Role -> permission set (Req 4.2, 4.3).
_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "org_admin": frozenset(Permission),  # all permissions
    "analyst": frozenset(
        {
            Permission.SEARCH,
            Permission.ANSWER,
            Permission.CONTENTS,
            Permission.INDEX,
            Permission.RESEARCH,
            Permission.PIPELINE_READ,
            Permission.PIPELINE_WRITE,
            Permission.SESSION_WRITE,
        }
    ),
    "auditor": frozenset({Permission.AUDIT_READ, Permission.AUDIT_EXPORT}),
    "read_only": frozenset(
        {Permission.SEARCH, Permission.ANSWER, Permission.CONTENTS, Permission.PIPELINE_READ}
    ),
    # Machine API-key clients: full data plane, no admin/audit-export.
    "service": frozenset(
        {
            Permission.SEARCH,
            Permission.ANSWER,
            Permission.CONTENTS,
            Permission.INDEX,
            Permission.RESEARCH,
            Permission.PIPELINE_READ,
            Permission.PIPELINE_WRITE,
            Permission.SESSION_WRITE,
        }
    ),
}


class AuthorizationError(Exception):
    """Raised when a principal lacks a required permission (mapped to 403)."""

    def __init__(self, permission: Permission) -> None:
        self.code = "forbidden"
        self.permission = permission
        self.message = "You do not have permission to perform this action."
        super().__init__(self.message)


def permissions_for_roles(roles: tuple[str, ...]) -> frozenset[Permission]:
    """Union of permissions granted by the given roles (unknown roles contribute none)."""
    granted: set[Permission] = set()
    for role in roles:
        granted |= _ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


def has_permission(principal: Principal | None, permission: Permission) -> bool:
    """True if the principal's roles grant ``permission``."""
    if principal is None:
        return False
    return permission in permissions_for_roles(principal.roles)


def require_permission(principal: Principal | None, permission: Permission) -> None:
    """Raise :class:`AuthorizationError` if the principal lacks ``permission``."""
    if not has_permission(principal, permission):
        raise AuthorizationError(permission)
