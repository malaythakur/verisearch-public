"""FastAPI application factory for the API Gateway.

Creates a configured FastAPI instance with the middleware chain:
  request_id → auth → rate_limit → pii_redact → route

Middleware is registered outermost-first, meaning the first middleware added
is the outermost (executed first on request, last on response). In Starlette/FastAPI,
middleware added later wraps earlier middleware, so we add them in reverse order:
  - PII redact (innermost, closest to route handlers)
  - Rate limit
  - Auth
  - Request ID (outermost, first to execute)

This ensures the execution order on request is:
  Request → RequestId → Auth → RateLimit → PiiRedact → Route Handler
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from backend.api_gateway.errors import ErrorHandlingMiddleware, register_exception_handlers
from backend.api_gateway.middleware.auth import AuthMiddleware
from backend.api_gateway.middleware.pii_redact import PiiRedactMiddleware
from backend.api_gateway.middleware.rate_limit import RateLimitMiddleware
from backend.api_gateway.middleware.request_id import RequestIdMiddleware

if TYPE_CHECKING:
    from backend.auth.service import AuthService
    from backend.api_gateway.middleware.rate_limit import RateLimitChecker


def create_app(
    *,
    auth_service: AuthService | None = None,
    rate_limiter: RateLimitChecker | None = None,
    providers: object | None = None,
    settings: object | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        auth_service: The AuthService instance for authentication middleware.
            If None, a no-op auth service is used (useful for testing health endpoints).
        rate_limiter: The rate limiter instance for rate limit middleware.
            If None, attempts to connect to Redis via REDIS_URL env var.
            Falls back to pass-through if Redis is unavailable.
        providers: Optional pre-built platform Providers bundle. If None, built from
            settings via build_providers().
        settings: Optional Settings instance. If None, a Settings() is loaded from env.

    Returns:
        A configured FastAPI application with middleware chain and routes.
    """
    # Resolve settings and validate mode-required configuration (fail-fast, Req 1.5).
    from backend.config.settings import Settings as _Settings

    if settings is None:
        settings = _Settings()
    settings.validate_for_mode()

    # Build platform providers (secrets/kms/object-store/identity) if not injected.
    if providers is None:
        from backend.providers import build_providers

        providers = build_providers(settings)

    # Resolve runtime secrets via the SecretsProvider and seed log redaction
    # (Phase 1, Req 2.2/2.5/2.6). Fail-fast if a required secret is unresolved.
    _resolve_secrets_at_startup(settings, providers)

    # Auto-connect to Redis for rate limiting if REDIS_URL is set
    if rate_limiter is None:
        rate_limiter = _create_redis_rate_limiter()
    app = FastAPI(
        title="Agentic Research Search Engine",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/v1/openapi.json",
    )

    # Make settings + providers available to routes via app.state.
    app.state.settings = settings
    app.state.providers = providers

    # Register routes
    _register_routes(app)

    # Register exception handlers for uniform error responses
    register_exception_handlers(app)

    # Register middleware in reverse order (last added = outermost = first executed)
    # Execution order on request:
    #   RequestId → Auth → SingleTenant → RateLimit → PiiRedact → ErrorHandling → Handler
    #
    # Starlette processes middleware in LIFO order (last added middleware runs first),
    # so we add them in reverse of desired execution order:
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(PiiRedactMiddleware)
    app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)

    # Metrics middleware records per-endpoint rate/error/latency (Phase 9, Req 9.2).
    from backend.api_gateway.middleware.metrics import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)

    # Single-tenant enforcement runs after auth resolves tenant_id (so it is added
    # before AuthMiddleware here, given LIFO ordering). Only in single-tenant modes.
    if settings.is_single_tenant():
        from backend.api_gateway.middleware.single_tenant import SingleTenantMiddleware

        app.add_middleware(
            SingleTenantMiddleware, dedicated_tenant_id=settings.dedicated_tenant_id
        )

    if auth_service is not None:
        app.add_middleware(
            AuthMiddleware,
            auth_service=auth_service,
            identity_provider=getattr(providers, "identity", None),
            sso_required=bool(getattr(settings, "sso_required", False)),
        )
    else:
        # No real API-key AuthService (factory launched with no args). Wire the
        # configured identity provider so the SSO/OIDC (human) plane works — e.g.
        # Clerk Google sign-in. The machine-plane fallback REJECTS unauthenticated
        # requests (login required), so business endpoints are closed by default.
        app.add_middleware(
            AuthMiddleware,
            auth_service=_LoginRequiredAuthService(),
            identity_provider=getattr(providers, "identity", None),
            sso_required=bool(getattr(settings, "sso_required", False)),
        )

    app.add_middleware(RequestIdMiddleware)

    # Security middleware is outermost: HTTPS guard runs first on request, and
    # security headers attach on every response (Phase 2, Req 3.1 / 14.7).
    import os as _os

    _is_prod = _os.environ.get("APP_ENV", "dev").lower() != "dev"
    from backend.api_gateway.middleware.security import SecurityMiddleware

    app.add_middleware(SecurityMiddleware, https_only=_is_prod, hsts=_is_prod)

    # CORS is the OUTERMOST middleware so it answers preflight (OPTIONS) requests
    # and attaches Access-Control-* headers before auth/security run. Allowed
    # origins come from CORS_ALLOW_ORIGINS (comma-separated); defaults to the local
    # dev frontend. The browser app needs this to call the API cross-origin.
    from fastapi.middleware.cors import CORSMiddleware

    _origins_raw = _os.environ.get(
        "CORS_ALLOW_ORIGINS", "http://localhost:3010,http://localhost:3000"
    )
    _allow_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-Id",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-Index-Version",
        ],
    )

    return app


def _register_routes(app: FastAPI) -> None:
    """Register API routes on the FastAPI application."""
    from backend.api_gateway.routes import router as v1_router
    from backend.api_gateway.mcp_sse import mcp_router

    app.include_router(v1_router)
    app.include_router(mcp_router, prefix="/mcp")

    @app.get("/health")
    async def health_check() -> JSONResponse:
        """Health check endpoint — returns 200 with status info."""
        return JSONResponse(
            status_code=200,
            content={"status": "healthy", "version": "0.1.0"},
        )

    @app.get("/health/live")
    async def liveness() -> JSONResponse:
        """Liveness probe — process is up and serving (Phase 4, Req 8.4)."""
        return JSONResponse(status_code=200, content={"status": "alive"})

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        """Readiness probe — returns 503 when a required dependency is unavailable.

        Checks database reachability (Req 8.4). Redis/OpenSearch are optional in the
        current deployment and degrade gracefully, so they do not fail readiness.
        """
        from backend.api_gateway.persistence import DatabasePool

        checks: dict[str, str] = {}
        db_ok = await DatabasePool.health_check()
        checks["database"] = "ok" if db_ok else "unavailable"

        ready = db_ok
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus metrics exposition (Phase 9, Req 9.2)."""
        from backend.api_gateway.middleware.metrics import get_registry

        return Response(
            content=get_registry().render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )


class _NoOpAuthService:
    """A no-op auth service that always authenticates successfully.

    Used ONLY in tests that inject it explicitly (e.g. health-endpoint tests that
    need no database). It is never used as the default fallback in the running
    app — see ``_LoginRequiredAuthService`` for that.
    """

    async def authenticate(self, headers: dict[str, str], **kwargs) -> object:  # noqa: ANN003, ANN001
        """Always return a successful auth result."""
        from backend.auth.service import AuthResult

        return AuthResult(tenant_id="test-tenant", api_key_id="test-key")


class _LoginRequiredAuthService:
    """Machine-plane fallback that rejects every request.

    Used when the app is constructed without a real API-key ``AuthService`` (the
    default factory launch). Combined with the SSO/OIDC plane, this enforces
    "login to act": a request with a valid SSO token is authenticated by the
    identity provider before this service is consulted; any request that reaches
    here has no valid login and is rejected with 401.

    Public paths (/health, /docs, /metrics) skip auth entirely and never reach
    this service.
    """

    async def authenticate(self, headers: dict[str, str], **kwargs) -> object:  # noqa: ANN003, ANN001
        from backend.auth.service import AuthError

        return AuthError(
            code="login_required",
            message="Authentication required. Sign in to continue.",
        )


def _resolve_secrets_at_startup(settings: object, providers: object) -> None:
    """Resolve runtime secrets via the provider and seed log redaction (Phase 1).

    Runs the async resolution on a fresh event loop (create_app is sync). Fails fast
    if a required-in-prod secret cannot be resolved (Req 2.5). Registers resolved
    secret values with the log-redaction filter so they never appear in logs (Req 2.6).
    """
    import asyncio

    from backend.providers.secret_resolution import resolve_secrets
    from backend.providers.log_redaction import register_secret_values

    secrets_provider = getattr(providers, "secrets", None)
    if secrets_provider is None:
        return

    async def _run() -> dict[str, str]:
        return await resolve_secrets(settings, secrets_provider)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In an already-running loop (rare for app construction); skip eager
            # resolution and rely on env values already present.
            resolved = {}
        else:
            resolved = loop.run_until_complete(_run())
    except RuntimeError:
        resolved = asyncio.run(_run())

    if register_secret_values is not None and resolved:
        register_secret_values(set(resolved.values()))


def _create_redis_rate_limiter():
    """Create a Redis-backed rate limiter if REDIS_URL is set.

    Returns None (which triggers pass-through) if Redis is unavailable.
    """
    import os

    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None

    try:
        from redis.asyncio import Redis
        from backend.rate_limiter.token_bucket import TokenBucketRateLimiter

        # Handle rediss:// (TLS) URLs
        redis_client = Redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
        )
        return TokenBucketRateLimiter(redis_client, default_limit_per_minute=60)
    except Exception:
        return None
