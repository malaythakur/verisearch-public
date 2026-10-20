"""Observability package (Phase 9).

Re-exports the request metrics registry/middleware and the SLO definitions. Logging
setup with secret/PII redaction lives with the structlog configuration; metrics live
in the api_gateway middleware so they sit on the request path.
"""

from backend.observability.slo import SLO_TARGETS, SLOTarget

__all__ = ["SLO_TARGETS", "SLOTarget"]
