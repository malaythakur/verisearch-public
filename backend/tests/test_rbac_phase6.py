"""Tests for Enterprise Hardening Phase 6: RBAC."""

import pytest

from backend.auth.rbac import (
    AuthorizationError,
    Permission,
    has_permission,
    permissions_for_roles,
    require_permission,
)
from backend.providers.interfaces import Principal


def _principal(*roles: str) -> Principal:
    return Principal(tenant_id="t", subject="u", roles=tuple(roles), auth_kind="human")


# ---------------------------------------------------------------------------
# Role -> permission matrix (Req 4.2, 4.3)
# ---------------------------------------------------------------------------


class TestRoleMatrix:
    def test_org_admin_has_all(self):
        perms = permissions_for_roles(("org_admin",))
        for p in Permission:
            assert p in perms

    def test_analyst_can_work_not_admin(self):
        p = _principal("analyst")
        assert has_permission(p, Permission.SEARCH)
        assert has_permission(p, Permission.INDEX)
        assert has_permission(p, Permission.RESEARCH)
        assert not has_permission(p, Permission.ORG_MANAGE)
        assert not has_permission(p, Permission.APIKEY_MANAGE)
        assert not has_permission(p, Permission.AUDIT_READ)

    def test_auditor_is_read_only_audit(self):
        p = _principal("auditor")
        assert has_permission(p, Permission.AUDIT_READ)
        assert has_permission(p, Permission.AUDIT_EXPORT)
        # No data mutation (Req 4.4)
        assert not has_permission(p, Permission.INDEX)
        assert not has_permission(p, Permission.SEARCH)
        assert not has_permission(p, Permission.PIPELINE_WRITE)
        assert not has_permission(p, Permission.ORG_MANAGE)

    def test_read_only_role(self):
        p = _principal("read_only")
        assert has_permission(p, Permission.SEARCH)
        assert has_permission(p, Permission.ANSWER)
        assert not has_permission(p, Permission.INDEX)
        assert not has_permission(p, Permission.PIPELINE_WRITE)

    def test_service_role_data_plane_no_admin(self):
        p = _principal("service")
        assert has_permission(p, Permission.SEARCH)
        assert has_permission(p, Permission.INDEX)
        assert not has_permission(p, Permission.ORG_MANAGE)
        assert not has_permission(p, Permission.AUDIT_EXPORT)

    def test_unknown_role_grants_nothing(self):
        assert permissions_for_roles(("wizard",)) == frozenset()

    def test_multiple_roles_union(self):
        p = _principal("read_only", "auditor")
        assert has_permission(p, Permission.SEARCH)  # from read_only
        assert has_permission(p, Permission.AUDIT_READ)  # from auditor


# ---------------------------------------------------------------------------
# require_permission
# ---------------------------------------------------------------------------


class TestRequirePermission:
    def test_allows_when_permitted(self):
        require_permission(_principal("analyst"), Permission.SEARCH)  # no raise

    def test_raises_when_denied(self):
        with pytest.raises(AuthorizationError):
            require_permission(_principal("read_only"), Permission.INDEX)

    def test_none_principal_denied(self):
        with pytest.raises(AuthorizationError):
            require_permission(None, Permission.SEARCH)

    def test_error_shape(self):
        try:
            require_permission(_principal("auditor"), Permission.INDEX)
        except AuthorizationError as e:
            assert e.code == "forbidden"
            assert e.permission == Permission.INDEX


# ---------------------------------------------------------------------------
# Route enforcement via the dependency (Req 4.3)
# ---------------------------------------------------------------------------


def _build_app(principal: Principal | None):
    from fastapi import Depends, FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    from backend.api_gateway.errors import register_exception_handlers
    from backend.api_gateway.rbac_dep import requires

    app = FastAPI()
    register_exception_handlers(app)

    class _InjectPrincipal(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # noqa: ANN001, ANN201
            if principal is not None:
                request.state.principal = principal
            return await call_next(request)

    app.add_middleware(_InjectPrincipal)

    @app.post("/v1/index", dependencies=[Depends(requires(Permission.INDEX))])
    async def index():  # noqa: ANN202
        return JSONResponse({"ok": True})

    @app.get("/v1/audit", dependencies=[Depends(requires(Permission.AUDIT_READ))])
    async def audit():  # noqa: ANN202
        return JSONResponse({"ok": True})

    return app


class TestRouteEnforcement:
    @pytest.mark.asyncio
    async def test_analyst_can_index(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(_principal("analyst"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/index")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_auditor_cannot_index(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(_principal("auditor"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/index")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"

    @pytest.mark.asyncio
    async def test_auditor_can_read_audit(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(_principal("auditor"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/audit")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_analyst_cannot_read_audit(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(_principal("analyst"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/audit")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_principal_denied(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/index")
        assert resp.status_code == 403
