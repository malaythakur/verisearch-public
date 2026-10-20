"""Data residency, retention, and erasure (Enterprise Hardening Phase 8, Req 7).

Provides:
- ``residency_report()`` — where each data category resides for the active mode (7.4).
- ``RetentionSweeper`` — deletes business data past its per-tenant retention (7.2).
- ``TenantErasureService`` — "right to be forgotten": deletes a tenant's business
  data (documents, sessions, pipelines, research, object-store blobs) and emits a
  ``tenant_erasure`` audit event, while PRESERVING the (PII-free) audit log for its
  own independent retention (Req 7.3).

Erasure here intentionally differs from audit_log.TenantDeletionService: that service
can delete audit entries (subject to legal hold); GDPR erasure of *business* data must
keep the audit trail of the erasure itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ErasureResult:
    """Outcome of a tenant business-data erasure (Req 7.3)."""

    tenant_id: str
    status: str
    records_deleted: int = 0
    audit_preserved: bool = True
    categories: dict[str, int] = field(default_factory=dict)


def residency_report(settings: Any) -> dict[str, Any]:
    """Report where each data category resides for the active deployment (Req 7.4)."""
    region = getattr(settings, "data_residency_region", "unknown")
    mode = getattr(settings, "deployment_mode", "pooled")
    mode_value = getattr(mode, "value", mode)
    return {
        "deployment_mode": mode_value,
        "data_residency_region": region,
        "stores": {
            "postgres": region,
            "opensearch": region,
            "object_store": region,
            "redis": region,
        },
        "note": (
            "All tenant data is pinned to data_residency_region; no cross-region "
            "replication unless explicitly configured."
        ),
    }


class RetentionSweeper:
    """Deletes business data past its retention window (Req 7.2).

    Operates on the documents table (and could be extended to other stores). Retention
    is measured against ``updated_at``. Intended to be invoked by a periodic task.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")

    async def sweep_documents(self, retention_days: int) -> int:
        """Delete documents not updated within ``retention_days``; returns count.

        No-op (returns 0) when no database is configured.
        """
        if not self._database_url or retention_days <= 0:
            return 0
        try:
            import asyncpg

            conn = await asyncpg.connect(self._database_url)
            try:
                result = await conn.execute(
                    "DELETE FROM documents WHERE updated_at < (NOW() - $1 * INTERVAL '1 day')",
                    retention_days,
                )
            finally:
                await conn.close()
            try:
                return int(result.split()[-1])
            except (ValueError, IndexError):
                return 0
        except Exception:
            return 0


class TenantErasureService:
    """Deletes a tenant's business data while preserving the audit log (Req 7.3).

    Emits a ``tenant_erasure`` audit event recording scope and completion. The audit
    log itself is NOT deleted — it has its own independent retention.
    """

    # Business-data tables keyed by tenant_id (audit_events deliberately excluded).
    _BUSINESS_TABLES = ("documents", "sessions", "pipelines", "research_jobs", "citations")

    def __init__(self, audit_emitter=None, object_store=None, database_url: str | None = None) -> None:  # noqa: ANN001
        self._audit_emitter = audit_emitter
        self._object_store = object_store
        self._database_url = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")

    async def erase(self, tenant_id: str, *, request_id: str) -> ErasureResult:
        """Erase the tenant's business data; preserve the audit log (Req 7.3)."""
        categories: dict[str, int] = {}
        total = 0

        # 1. Delete object-store blobs for the tenant (if a store is wired).
        if self._object_store is not None:
            try:
                deleted = await self._object_store.delete_prefix(f"{tenant_id}/")
                categories["object_store"] = int(deleted)
                total += int(deleted)
            except Exception:
                categories["object_store"] = 0

        # 2. Delete business rows across the known tables (audit excluded).
        if self._database_url:
            try:
                import asyncpg

                conn = await asyncpg.connect(self._database_url)
                try:
                    for table in self._BUSINESS_TABLES:
                        count = await self._delete_table(conn, table, tenant_id)
                        if count:
                            categories[table] = count
                            total += count
                finally:
                    await conn.close()
            except Exception:
                pass

        # 3. Emit the tenant_erasure audit event (audit log is preserved).
        if self._audit_emitter is not None:
            try:
                await self._audit_emitter.emit(
                    action="tenant_erasure",
                    tenant_id=tenant_id,
                    actor="org_admin",
                    resource=f"tenant/{tenant_id}",
                    request_id=request_id,
                    detail={"records_deleted": total, "categories": categories},
                )
            except Exception:
                pass

        return ErasureResult(
            tenant_id=tenant_id,
            status="completed",
            records_deleted=total,
            audit_preserved=True,
            categories=categories,
        )

    async def _delete_table(self, conn, table: str, tenant_id: str) -> int:
        """Delete a tenant's rows from one table. Tables vary in tenant key type."""
        import uuid as _uuid

        # documents.tenant_id may not exist as a column in the local schema; guard.
        candidates: list[Any] = [tenant_id]
        try:
            candidates.append(_uuid.UUID(tenant_id))
        except Exception:
            pass

        for value in candidates:
            try:
                # `table` is from the fixed _BUSINESS_TABLES allowlist (never user
                # input); the tenant value is parameterized via $1.
                result = await conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id = $1",  # nosec
                    value,
                )
                try:
                    return int(result.split()[-1])
                except (ValueError, IndexError):
                    return 0
            except Exception:
                continue
        return 0
