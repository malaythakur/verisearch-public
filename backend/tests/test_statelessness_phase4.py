"""Tests for Enterprise Hardening Phase 4: health probes + load-shedding."""

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api_gateway.app import create_app
from backend.api_gateway.persistence import DatabasePool, PoolExhaustedError


class _FakeAuthSuccess:
    async def authenticate(self, headers, **kwargs):  # noqa: ANN001, ANN003
        from backend.auth.service import AuthResult

        return AuthResult(tenant_id="test-tenant", api_key_id="k")


# ---------------------------------------------------------------------------
# Health probes (Req 8.4)
# ---------------------------------------------------------------------------


class TestHealthProbes:
    @pytest.mark.asyncio
    async def test_liveness_always_ok(self):
        app = create_app(auth_service=_FakeAuthSuccess())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    @pytest.mark.asyncio
    async def test_readiness_ok_when_no_db_configured(self):
        # In-memory mode (no DATABASE_URL) is a valid deployment → ready.
        app = create_app(auth_service=_FakeAuthSuccess())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert resp.json()["checks"]["database"] == "ok"

    @pytest.mark.asyncio
    async def test_readiness_503_when_db_unavailable(self):
        app = create_app(auth_service=_FakeAuthSuccess())

        async def _fake_unhealthy(*args, **kwargs):
            return False

        with patch.object(DatabasePool, "health_check", _fake_unhealthy):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"
        assert resp.json()["checks"]["database"] == "unavailable"

    @pytest.mark.asyncio
    async def test_probes_skip_rate_limit_and_auth(self):
        # No Authorization header; probes must still answer.
        app = create_app(auth_service=_FakeAuthSuccess())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health/live")).status_code == 200


# ---------------------------------------------------------------------------
# health_check helper (Req 8.4)
# ---------------------------------------------------------------------------


class TestHealthCheckHelper:
    @pytest.mark.asyncio
    async def test_returns_true_without_database_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            assert await DatabasePool.health_check() is True


# ---------------------------------------------------------------------------
# Load-shedding (Req 8.3)
# ---------------------------------------------------------------------------


class TestLoadShedding:
    @pytest.mark.asyncio
    async def test_acquire_or_shed_raises_when_no_pool(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            # Reset pool state so get_pool returns None.
            DatabasePool._pool = None
            DatabasePool._initialized = False
            with pytest.raises(PoolExhaustedError):
                await DatabasePool.acquire_or_shed(timeout=0.1)

    def test_pool_exhausted_error_shape(self):
        err = PoolExhaustedError()
        assert err.code == "service_overloaded"
        assert "pool" in err.message.lower()
