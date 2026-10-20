"""Request metrics middleware + Prometheus exposition (Phase 9, Req 9.2).

Records per-endpoint request count, error count, and latency percentiles in a
self-contained in-process registry and exposes them in Prometheus text format. This
is dependency-free (no prometheus_client required) so it runs anywhere; in production
the same counters can be scraped at /metrics or shipped via an OTLP exporter.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Latency histogram buckets (seconds) for the request duration histogram.
_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
)


@dataclass
class _EndpointStats:
    count: int = 0
    errors: int = 0
    durations: list[float] = field(default_factory=list)

    def observe(self, duration_s: float, is_error: bool) -> None:
        self.count += 1
        if is_error:
            self.errors += 1
        # Bound memory: keep a rolling window of recent samples for percentiles.
        self.durations.append(duration_s)
        if len(self.durations) > 2000:
            self.durations = self.durations[-2000:]

    def percentile(self, p: float) -> float:
        if not self.durations:
            return 0.0
        ordered = sorted(self.durations)
        idx = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
        return ordered[idx]


class MetricsRegistry:
    """Thread-safe per-endpoint metrics registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_endpoint: dict[str, _EndpointStats] = {}

    def record(self, method: str, endpoint: str, status: int, duration_s: float) -> None:
        key = f"{method} {endpoint}"
        with self._lock:
            stats = self._by_endpoint.setdefault(key, _EndpointStats())
            stats.observe(duration_s, is_error=status >= 500)

    def render_prometheus(self) -> str:
        """Render current metrics in Prometheus text exposition format."""
        lines: list[str] = []
        lines.append("# HELP http_requests_total Total HTTP requests by endpoint.")
        lines.append("# TYPE http_requests_total counter")
        with self._lock:
            snapshot = {k: (v.count, v.errors, v.percentile(50), v.percentile(95), v.percentile(99))
                        for k, v in self._by_endpoint.items()}
        for key, (count, _errors, _p50, _p95, _p99) in snapshot.items():
            method, _, endpoint = key.partition(" ")
            lines.append(
                f'http_requests_total{{method="{method}",endpoint="{endpoint}"}} {count}'
            )
        lines.append("# HELP http_request_errors_total Total 5xx responses by endpoint.")
        lines.append("# TYPE http_request_errors_total counter")
        for key, (_count, errors, _p50, _p95, _p99) in snapshot.items():
            method, _, endpoint = key.partition(" ")
            lines.append(
                f'http_request_errors_total{{method="{method}",endpoint="{endpoint}"}} {errors}'
            )
        lines.append("# HELP http_request_duration_seconds Request latency percentiles by endpoint.")
        lines.append("# TYPE http_request_duration_seconds summary")
        for key, (_count, _errors, p50, p95, p99) in snapshot.items():
            method, _, endpoint = key.partition(" ")
            base = f'http_request_duration_seconds{{method="{method}",endpoint="{endpoint}"'
            lines.append(f'{base},quantile="0.5"}} {p50:.6f}')
            lines.append(f'{base},quantile="0.95"}} {p95:.6f}')
            lines.append(f'{base},quantile="0.99"}} {p99:.6f}')
        return "\n".join(lines) + "\n"

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return a plain-dict snapshot (for tests / JSON)."""
        with self._lock:
            return {
                key: {
                    "count": stats.count,
                    "errors": stats.errors,
                    "p50": stats.percentile(50),
                    "p95": stats.percentile(95),
                    "p99": stats.percentile(99),
                }
                for key, stats in self._by_endpoint.items()
            }


# Process-global registry.
_REGISTRY = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _REGISTRY


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records request rate, errors, and latency per endpoint (Req 9.2)."""

    def __init__(self, app, registry: MetricsRegistry | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self._registry = registry or _REGISTRY

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            # Use the route template when available to avoid unbounded cardinality.
            endpoint = request.url.path
            route = request.scope.get("route")
            if route is not None and getattr(route, "path", None):
                endpoint = route.path
            self._registry.record(request.method, endpoint, status, duration)
