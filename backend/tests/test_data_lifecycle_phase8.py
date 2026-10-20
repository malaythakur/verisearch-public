"""Tests for Enterprise Hardening Phase 8: residency, retention, erasure."""

import pytest

from backend.api_gateway.data_lifecycle import (
    RetentionSweeper,
    TenantErasureService,
    residency_report,
)
from backend.config.settings import DeploymentMode, Settings


# ---------------------------------------------------------------------------
# Residency report (Req 7.4)
# ---------------------------------------------------------------------------


class TestResidencyReport:
    def test_reports_region_and_mode(self):
        s = Settings(_env_file=None, data_residency_region="eu-west-1")
        report = residency_report(s)
        assert report["data_residency_region"] == "eu-west-1"
        assert report["deployment_mode"] == "pooled"
        assert report["stores"]["postgres"] == "eu-west-1"
        assert report["stores"]["object_store"] == "eu-west-1"

    def test_reports_dedicated_mode(self):
        s = Settings(
            _env_file=None,
            deployment_mode=DeploymentMode.DEDICATED_VPC,
            dedicated_tenant_id="bank-1",
            secrets_backend="aws",
            kms_backend="aws",
            kms_key_id="arn:aws:kms:eu-west-1:1:key/x",
            data_residency_region="eu-central-1",
        )
        report = residency_report(s)
        assert report["deployment_mode"] == "dedicated_vpc"
        assert report["data_residency_region"] == "eu-central-1"


# ---------------------------------------------------------------------------
# Retention sweep (Req 7.2)
# ---------------------------------------------------------------------------


class TestRetentionSweeper:
    @pytest.mark.asyncio
    async def test_noop_without_database(self):
        sweeper = RetentionSweeper(database_url="")
        assert await sweeper.sweep_documents(30) == 0

    @pytest.mark.asyncio
    async def test_noop_with_nonpositive_retention(self):
        sweeper = RetentionSweeper(database_url="postgresql://x")
        assert await sweeper.sweep_documents(0) == 0


# ---------------------------------------------------------------------------
# Tenant erasure (Req 7.3)
# ---------------------------------------------------------------------------


class _FakeObjectStore:
    def __init__(self):
        self.deleted_prefixes: list[str] = []

    async def delete_prefix(self, prefix: str) -> int:
        self.deleted_prefixes.append(prefix)
        return 5  # pretend 5 blobs deleted


class _FakeAudit:
    def __init__(self):
        self.events: list[dict] = []

    async def emit(self, **kwargs):  # noqa: ANN003
        self.events.append(kwargs)


class TestTenantErasure:
    @pytest.mark.asyncio
    async def test_deletes_object_store_blobs(self):
        store = _FakeObjectStore()
        svc = TenantErasureService(object_store=store, database_url="")
        result = await svc.erase("bank-1", request_id="r" * 16)
        assert store.deleted_prefixes == ["bank-1/"]
        assert result.categories.get("object_store") == 5
        assert result.records_deleted >= 5

    @pytest.mark.asyncio
    async def test_emits_tenant_erasure_audit_event(self):
        audit = _FakeAudit()
        svc = TenantErasureService(audit_emitter=audit, object_store=_FakeObjectStore(), database_url="")
        await svc.erase("bank-1", request_id="r" * 16)
        assert len(audit.events) == 1
        assert audit.events[0]["action"] == "tenant_erasure"
        assert audit.events[0]["tenant_id"] == "bank-1"

    @pytest.mark.asyncio
    async def test_audit_is_preserved(self):
        svc = TenantErasureService(object_store=_FakeObjectStore(), database_url="")
        result = await svc.erase("bank-1", request_id="r" * 16)
        # Erasure never deletes the audit log itself (Req 7.3).
        assert result.audit_preserved is True
        assert "audit_events" not in TenantErasureService._BUSINESS_TABLES

    @pytest.mark.asyncio
    async def test_status_completed(self):
        svc = TenantErasureService(object_store=_FakeObjectStore(), database_url="")
        result = await svc.erase("bank-1", request_id="r" * 16)
        assert result.status == "completed"
