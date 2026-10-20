"""Tests for Enterprise Hardening Phase 5: OIDC SSO + dual-plane auth."""

import time

import pytest

from backend.providers.interfaces import IdentityError, Principal
from backend.providers.oidc_provider import OidcIdentityProvider


# ---------------------------------------------------------------------------
# RSA keypair + JWKS fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(rsa_key):
    import jwt
    from jwt.algorithms import RSAAlgorithm
    import json

    public_jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    public_jwk["kid"] = "test-key-1"
    public_jwk.setdefault("alg", "RS256")
    public_jwk.setdefault("use", "sig")
    return {"keys": [public_jwk]}


def _make_token(rsa_key, *, issuer, audience, sub="user-1", extra=None, exp_delta=3600):
    import jwt

    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "iat": now,
        "exp": now + exp_delta,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, rsa_key, algorithm="RS256", headers={"kid": "test-key-1"})


ISSUER = "https://idp.example.com"
AUDIENCE = "verisearch-client"


def _provider(jwks):
    p = OidcIdentityProvider(issuer=ISSUER, audience=AUDIENCE)
    p._set_jwks_for_test(jwks)
    return p


# ---------------------------------------------------------------------------
# OIDC token validation (Req 4.1, 4.7)
# ---------------------------------------------------------------------------


class TestOidcValidation:
    @pytest.mark.asyncio
    async def test_valid_token_returns_principal(self, rsa_key, jwks):
        token = _make_token(
            rsa_key, issuer=ISSUER, audience=AUDIENCE,
            extra={"tenant_id": "bank-123", "roles": ["analyst", "auditor"]},
        )
        principal = await _provider(jwks).verify_assertion(token)
        assert isinstance(principal, Principal)
        assert principal.tenant_id == "bank-123"
        assert principal.subject == "user-1"
        assert principal.auth_kind == "human"
        assert principal.has_role("analyst")
        assert principal.has_role("auditor")

    @pytest.mark.asyncio
    async def test_space_separated_roles_claim(self, rsa_key, jwks):
        token = _make_token(
            rsa_key, issuer=ISSUER, audience=AUDIENCE,
            extra={"roles": "analyst auditor"},
        )
        principal = await _provider(jwks).verify_assertion(token)
        assert principal.has_role("analyst")
        assert principal.has_role("auditor")

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, rsa_key, jwks):
        token = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, exp_delta=-10)
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion(token)

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self, rsa_key, jwks):
        token = _make_token(rsa_key, issuer="https://evil.example.com", audience=AUDIENCE)
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion(token)

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self, rsa_key, jwks):
        token = _make_token(rsa_key, issuer=ISSUER, audience="some-other-client")
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion(token)

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self, jwks):
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion("")

    @pytest.mark.asyncio
    async def test_malformed_token_rejected(self, jwks):
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion("not.a.jwt")

    @pytest.mark.asyncio
    async def test_token_signed_by_unknown_key_rejected(self, jwks):
        # Sign with a different key than the one in the JWKS.
        from cryptography.hazmat.primitives.asymmetric import rsa

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _make_token(other_key, issuer=ISSUER, audience=AUDIENCE)
        with pytest.raises(IdentityError):
            await _provider(jwks).verify_assertion(token)


# ---------------------------------------------------------------------------
# Consumer mode (Clerk + Google): per-user corpus + default roles
# ---------------------------------------------------------------------------


def _consumer_provider(jwks):
    p = OidcIdentityProvider(
        issuer=ISSUER,
        audience=AUDIENCE,
        default_roles=("analyst",),
        tenant_from_subject=True,
    )
    p._set_jwks_for_test(jwks)
    return p


class TestConsumerOidc:
    @pytest.mark.asyncio
    async def test_subject_becomes_private_tenant(self, rsa_key, jwks):
        # No tenant claim -> tenant derived from subject = private per-user corpus.
        token = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="clerk_abc123")
        principal = await _consumer_provider(jwks).verify_assertion(token)
        assert principal.tenant_id == "user:clerk_abc123"
        assert principal.subject == "clerk_abc123"

    @pytest.mark.asyncio
    async def test_default_roles_applied_when_no_roles_claim(self, rsa_key, jwks):
        token = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="clerk_abc123")
        principal = await _consumer_provider(jwks).verify_assertion(token)
        assert principal.has_role("analyst")
        # Consumer users must NOT get admin/auditor by default.
        assert not principal.has_role("org_admin")
        assert not principal.has_role("auditor")

    @pytest.mark.asyncio
    async def test_two_users_get_distinct_tenants(self, rsa_key, jwks):
        prov = _consumer_provider(jwks)
        p1 = await prov.verify_assertion(
            _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="user-a")
        )
        p2 = await prov.verify_assertion(
            _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="user-b")
        )
        assert p1.tenant_id != p2.tenant_id

    @pytest.mark.asyncio
    async def test_explicit_tenant_claim_overrides_subject(self, rsa_key, jwks):
        # If the IdP DOES provide a tenant claim, it wins over the sub fallback.
        token = _make_token(
            rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="u1",
            extra={"tenant_id": "org-9"},
        )
        principal = await _consumer_provider(jwks).verify_assertion(token)
        assert principal.tenant_id == "org-9"

    @pytest.mark.asyncio
    async def test_explicit_roles_override_defaults(self, rsa_key, jwks):
        token = _make_token(
            rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="u1",
            extra={"roles": ["org_admin"]},
        )
        principal = await _consumer_provider(jwks).verify_assertion(token)
        assert principal.has_role("org_admin")
        assert not principal.has_role("analyst")


class TestConsumerCorpusIsolationE2E:
    """End-to-end proof (through the real AuthMiddleware) that two signed-in
    consumer users get isolated private corpora.

    This exercises the same path a live Clerk login takes: token -> middleware
    -> identity provider -> request.state.tenant_id -> tenant-scoped store. It
    proves user A cannot read user B's document and vice-versa.
    """

    def _build_isolated_app(self, jwks):
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from backend.api_gateway.middleware.auth import AuthMiddleware

        app = FastAPI()
        # Tenant-scoped in-memory store: {tenant_id: {doc_id: content}}
        store: dict[str, dict[str, str]] = {}

        @app.post("/v1/docs/{doc_id}")
        async def put_doc(doc_id: str, request: Request):  # noqa: ANN202
            tenant = request.state.tenant_id
            store.setdefault(tenant, {})[doc_id] = f"secret-of-{tenant}"
            return JSONResponse({"tenant": tenant, "doc_id": doc_id})

        @app.get("/v1/docs/{doc_id}")
        async def get_doc(doc_id: str, request: Request):  # noqa: ANN202
            tenant = request.state.tenant_id
            doc = store.get(tenant, {}).get(doc_id)
            if doc is None:
                # Uniform 404 — never disclose another tenant's resource.
                return JSONResponse(
                    {"error": {"code": "document_not_found", "message": "not found"}},
                    status_code=404,
                )
            return JSONResponse({"content": doc})

        app.add_middleware(
            AuthMiddleware,
            auth_service=_FakeApiKeyAuth(),
            identity_provider=_consumer_provider(jwks),
        )
        return app

    @pytest.mark.asyncio
    async def test_user_a_cannot_read_user_b_document(self, rsa_key, jwks):
        from httpx import ASGITransport, AsyncClient

        app = self._build_isolated_app(jwks)
        token_a = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="user-a")
        token_b = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, sub="user-b")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # User A indexes a private document.
            r = await client.post("/v1/docs/d1", headers={"x-sso-token": token_a})
            assert r.status_code == 200
            assert r.json()["tenant"] == "user:user-a"

            # User A can read their own document.
            r = await client.get("/v1/docs/d1", headers={"x-sso-token": token_a})
            assert r.status_code == 200
            assert r.json()["content"] == "secret-of-user:user-a"

            # User B CANNOT read user A's document — uniform 404.
            r = await client.get("/v1/docs/d1", headers={"x-sso-token": token_b})
            assert r.status_code == 404
            assert r.json()["error"]["code"] == "document_not_found"

            # User B's own corpus is independent.
            r = await client.post("/v1/docs/d1", headers={"x-sso-token": token_b})
            assert r.status_code == 200
            assert r.json()["tenant"] == "user:user-b"
            r = await client.get("/v1/docs/d1", headers={"x-sso-token": token_b})
            assert r.json()["content"] == "secret-of-user:user-b"


# ---------------------------------------------------------------------------
# Dual-plane auth middleware (Req 4.5, 4.6)
# ---------------------------------------------------------------------------


class _FakeApiKeyAuth:
    def __init__(self):
        self._audit_emitter = None

    async def authenticate(self, headers, **kwargs):  # noqa: ANN001, ANN003
        from backend.auth.service import AuthError, AuthResult

        if headers.get("authorization") == "Bearer valid-key-123456":
            return AuthResult(tenant_id="machine-tenant", api_key_id="key-1")
        return AuthError(code="invalid_token", message="bad key")


def _build_app(*, identity_provider=None, sso_required=False):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from backend.api_gateway.middleware.auth import AuthMiddleware

    app = FastAPI()

    @app.get("/v1/whoami")
    async def whoami(request_holder=None):  # noqa: ANN001, ANN202
        return JSONResponse({"ok": True})

    app.add_middleware(
        AuthMiddleware,
        auth_service=_FakeApiKeyAuth(),
        identity_provider=identity_provider,
        sso_required=sso_required,
    )
    return app


class TestDualPlaneAuth:
    @pytest.mark.asyncio
    async def test_api_key_plane_succeeds(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/whoami", headers={"authorization": "Bearer valid-key-123456"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sso_plane_succeeds(self, rsa_key, jwks):
        from httpx import ASGITransport, AsyncClient

        token = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, extra={"tenant_id": "bank-9"})
        app = _build_app(identity_provider=_provider(jwks))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/whoami", headers={"x-sso-token": token})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_sso_token_returns_401(self, jwks):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(identity_provider=_provider(jwks))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/whoami", headers={"x-sso-token": "bogus"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_sso_token"

    @pytest.mark.asyncio
    async def test_sso_required_rejects_api_key(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(sso_required=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/whoami", headers={"authorization": "Bearer valid-key-123456"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "sso_required"


class TestLoginRequiredFallback:
    """Option A: the default factory app closes all business endpoints.

    When the app is built with no real API-key AuthService, the machine-plane
    fallback must reject unauthenticated requests (login required) while still
    allowing the SSO/OIDC plane and keeping health/docs public.
    """

    @pytest.mark.asyncio
    async def test_no_credentials_rejected(self):
        from httpx import ASGITransport, AsyncClient
        from backend.api_gateway.app import create_app

        app = create_app()  # no auth_service => login-required fallback
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/me")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "login_required"

    @pytest.mark.asyncio
    async def test_health_still_public(self):
        from httpx import ASGITransport, AsyncClient
        from backend.api_gateway.app import create_app

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_sso_token_still_accepted(self, rsa_key, jwks, monkeypatch):
        """With OIDC configured, a valid SSO token authenticates even on the
        login-required fallback app."""
        from httpx import ASGITransport, AsyncClient
        from backend.api_gateway.app import create_app
        from backend.config.settings import Settings
        from backend.providers.interfaces import Providers
        from backend.providers.dev_providers import (
            EnvSecretsProvider,
            LocalDevKms,
            InMemoryObjectStore,
        )

        settings = Settings(
            _env_file=None,
            idp_kind="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
        )
        providers = Providers(
            secrets=EnvSecretsProvider(),
            kms=LocalDevKms(),
            object_store=InMemoryObjectStore(),
            identity=_provider(jwks),
        )
        app = create_app(settings=settings, providers=providers)

        @app.get("/v1/whoami-test")
        async def _whoami():  # noqa: ANN202
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": True})

        token = _make_token(rsa_key, issuer=ISSUER, audience=AUDIENCE, extra={"tenant_id": "bank-9"})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/whoami-test", headers={"x-sso-token": token})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Provider config validation
# ---------------------------------------------------------------------------


class TestOidcConfigValidation:
    def test_oidc_requires_issuer_and_audience(self):
        from backend.config.settings import Settings, ConfigurationError

        s = Settings(_env_file=None, idp_kind="oidc")
        with pytest.raises(ConfigurationError) as exc:
            s.validate_for_mode()
        assert "oidc_issuer" in str(exc.value)
        assert "oidc_audience" in str(exc.value)

    def test_oidc_valid_when_configured(self):
        from backend.config.settings import Settings

        s = Settings(
            _env_file=None,
            idp_kind="oidc",
            oidc_issuer="https://idp.example.com",
            oidc_audience="client-1",
        )
        s.validate_for_mode()  # should not raise
