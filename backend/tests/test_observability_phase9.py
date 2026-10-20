"""Tests for Enterprise Hardening Phase 9: metrics + SLOs."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api_gateway.app import create_app
from backend.api_gateway.middleware.metrics import MetricsRegistry
from backend.observability.slo import SLO_TARGETS, slo_as_dicts


class _FakeAuthSuccess:
    async def authenticate(self, headers, **kwargs):  # noqa: ANN001, ANN003
        from backend.auth.service import AuthResult

        return AuthResult(tenant_id="test-tenant", api_key_id="k")


# ---------------------------------------------------------------------------
# MetricsRegistry (Req 9.2)
# ---------------------------------------------------------------------------


class TestMetricsRegistry:
    def test_records_count_and_errors(self):
        reg = MetricsRegistry()
        reg.record("GET", "/v1/search", 200, 0.1)
        reg.record("GET", "/v1/search", 200, 0.2)
        reg.record("GET", "/v1/search", 500, 0.3)
        snap = reg.snapshot()["GET /v1/search"]
        assert snap["count"] == 3
        assert snap["errors"] == 1

    def test_percentiles_monotonic(self):
        reg = MetricsRegistry()
        for i in range(1, 101):
            reg.record("POST", "/v1/answer", 200, i / 100.0)
        snap = reg.snapshot()["POST /v1/answer"]
        assert snap["p50"] <= snap["p95"] <= snap["p99"]

    def test_render_prometheus_format(self):
        reg = MetricsRegistry()
        reg.record("GET", "/v1/search", 200, 0.05)
        text = reg.render_prometheus()
        assert "http_requests_total" in text
        assert "http_request_errors_total" in text
        assert "http_request_duration_seconds" in text
        assert 'endpoint="/v1/search"' in text


# ---------------------------------------------------------------------------
# /metrics endpoint + middleware integration
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_endpoint_exposed(self):
        app = create_app(auth_service=_FakeAuthSuccess())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Generate some traffic first.
            await client.get("/health")
            resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text

    @pytest.mark.asyncio
    async def test_metrics_public_no_auth(self):
        app = create_app(auth_service=_FakeAuthSuccess())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics")  # no Authorization header
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_request_recorded_in_metrics(self):
        app = create_app(auth_service=_FakeAuthSuccess())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health")
            resp = await client.get("/metrics")
        # The /health request should appear in the exposition.
        assert "/health" in resp.text


# ---------------------------------------------------------------------------
# SLO definitions (Req 9.4/9.5)
# ---------------------------------------------------------------------------


class TestSLO:
    def test_slo_targets_present(self):
        names = {s.name for s in SLO_TARGETS}
        assert "availability" in names
        assert "auth_resolution" in names
        assert "search_warm_cache" in names

    def test_slo_as_dicts(self):
        dicts = slo_as_dicts()
        assert all({"name", "description", "metric", "objective"} <= set(d) for d in dicts)
