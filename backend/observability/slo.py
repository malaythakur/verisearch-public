"""Service Level Objectives (Enterprise Hardening Phase 9, Req 9.4/9.5).

Documents the platform's latency/availability SLOs as data so they can be referenced
by dashboards, alerting, and the metrics endpoint. These mirror the SLO targets in the
original engine spec (R2.1, R3.2, R6.1, R7.1, R11.1, R13.1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SLOTarget:
    """A single SLO target."""

    name: str
    description: str
    metric: str
    objective: str


SLO_TARGETS: tuple[SLOTarget, ...] = (
    SLOTarget(
        name="availability",
        description="API availability over a rolling 30-day window",
        metric="successful_requests / total_requests",
        objective=">= 99.9%",
    ),
    SLOTarget(
        name="auth_resolution",
        description="Auth resolution latency",
        metric="auth_resolution_duration_seconds",
        objective="p95 <= 50ms",
    ),
    SLOTarget(
        name="search_warm_cache",
        description="Warm-cache search latency",
        metric="search_request_duration_seconds{cache=warm}",
        objective="p95 <= 800ms",
    ),
    SLOTarget(
        name="answer_first_token",
        description="Time to first streamed answer token",
        metric="answer_first_token_duration_seconds",
        objective="p95 <= 3s",
    ),
    SLOTarget(
        name="research_job_return",
        description="Research job_id return latency",
        metric="research_job_creation_duration_seconds",
        objective="p95 <= 1s",
    ),
    SLOTarget(
        name="filter_parser",
        description="Query filter parser latency (single core)",
        metric="parser_duration_seconds",
        objective="p95 <= 100ms",
    ),
    SLOTarget(
        name="ingest_freshness",
        description="Fetch-to-searchable latency",
        metric="ingest_pipeline_duration_seconds",
        objective="p95 <= 60min, p99 <= 4h",
    ),
)


def slo_as_dicts() -> list[dict[str, str]]:
    """Return the SLO targets as plain dicts (for JSON/docs)."""
    return [
        {"name": s.name, "description": s.description, "metric": s.metric, "objective": s.objective}
        for s in SLO_TARGETS
    ]
