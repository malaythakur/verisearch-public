"""Tests for Enterprise Hardening Phase 0: deployment modes + provider abstraction."""

import os
from unittest.mock import patch

import pytest

from backend.config.settings import (
    ConfigurationError,
    DeploymentMode,
    Settings,
)
from backend.providers import build_providers
from backend.providers.dev_providers import (
    EnvSecretsProvider,
    InMemoryObjectStore,
    LocalDevKms,
    NullIdentityProvider,
)
from backend.providers.interfaces import (
    IdentityError,
    Principal,
    SecretNotFoundError,
)


# ---------------------------------------------------------------------------
# Mode validation (Req 1.5)
# ---------------------------------------------------------------------------


class TestModeValidation:
    def test_pooled_defaults_are_valid(self):
        s = Settings(_env_file=None)
        s.validate_for_mode()  # should not raise

    def test_dedicated_requires_tenant_and_aws_backends(self):
        s = Settings(_env_file=None, deployment_mode=DeploymentMode.DEDICATED_VPC)
        with pytest.raises(ConfigurationError) as exc:
            s.validate_for_mode()
        msg = str(exc.value)
        assert "dedicated_tenant_id" in msg
        assert "secrets_backend" in msg
        assert "kms_backend" in msg

    def test_dedicated_valid_when_fully_configured(self):
        s = Settings(
            _env_file=None,
            deployment_mode=DeploymentMode.DEDICATED_VPC,
            dedicated_tenant_id="bank-123",
            secrets_backend="aws",
            kms_backend="aws",
            kms_key_id="arn:aws:kms:eu-west-1:111:key/abc",
        )
        s.validate_for_mode()  # should not raise

    def test_aws_kms_requires_key_id(self):
        s = Settings(_env_file=None, kms_backend="aws")
        with pytest.raises(ConfigurationError) as exc:
            s.validate_for_mode()
        assert "kms_key_id" in str(exc.value)

    def test_is_single_tenant(self):
        assert not Settings(_env_file=None).is_single_tenant()
        assert Settings(
            _env_file=None, deployment_mode=DeploymentMode.DEDICATED_VPC
        ).is_single_tenant()
        assert Settings(
            _env_file=None, deployment_mode=DeploymentMode.CUSTOMER_MANAGED
        ).is_single_tenant()


# ---------------------------------------------------------------------------
# Provider selection (Req 1.3)
# ---------------------------------------------------------------------------


class TestProviderSelection:
    def test_pooled_dev_providers(self):
        s = Settings(_env_file=None)  # env secrets, local kms, minio->in-memory, none idp
        providers = build_providers(s)
        assert isinstance(providers.secrets, EnvSecretsProvider)
        assert isinstance(providers.kms, LocalDevKms)
        assert isinstance(providers.object_store, InMemoryObjectStore)
        assert isinstance(providers.identity, NullIdentityProvider)

    def test_aws_backends_selected_but_lazy(self):
        # Selecting aws backends should construct providers without needing AWS creds
        # (boto3 clients are created lazily on first use).
        s = Settings(
            _env_file=None,
            secrets_backend="aws",
            kms_backend="aws",
            kms_key_id="arn:aws:kms:eu-west-1:111:key/abc",
            object_store_backend="s3",
            data_residency_region="eu-west-1",
        )
        providers = build_providers(s)
        assert providers.secrets.__class__.__name__ == "AwsSecretsManagerProvider"
        assert providers.kms.key_id == "arn:aws:kms:eu-west-1:111:key/abc"
        assert providers.object_store.__class__.__name__ == "S3ObjectStore"

    def test_sso_selection_requires_oidc_config(self):
        # OIDC is implemented (Phase 5); selecting it without issuer/audience is a
        # configuration error surfaced at provider construction.
        s = Settings(_env_file=None, idp_kind="oidc")
        with pytest.raises((ValueError, NotImplementedError)):
            build_providers(s)

    def test_saml_selection_not_implemented(self):
        s = Settings(_env_file=None, idp_kind="saml")
        with pytest.raises(NotImplementedError):
            build_providers(s)


# ---------------------------------------------------------------------------
# EnvSecretsProvider
# ---------------------------------------------------------------------------


class TestEnvSecretsProvider:
    @pytest.mark.asyncio
    async def test_get_secret(self):
        with patch.dict(os.environ, {"MY_SECRET": "s3cr3t"}, clear=False):
            p = EnvSecretsProvider()
            assert await p.get_secret("MY_SECRET") == "s3cr3t"

    @pytest.mark.asyncio
    async def test_missing_secret_raises(self):
        p = EnvSecretsProvider()
        with pytest.raises(SecretNotFoundError):
            await p.get_secret("DOES_NOT_EXIST_12345")

    @pytest.mark.asyncio
    async def test_get_secret_json(self):
        with patch.dict(os.environ, {"J": '{"a": 1}'}, clear=False):
            p = EnvSecretsProvider()
            assert await p.get_secret_json("J") == {"a": 1}


# ---------------------------------------------------------------------------
# LocalDevKms envelope encryption round-trip
# ---------------------------------------------------------------------------


class TestLocalDevKms:
    @pytest.mark.asyncio
    async def test_round_trip(self):
        kms = LocalDevKms()
        plaintext = b"sensitive document content"
        blob = await kms.encrypt(plaintext)
        assert blob.ciphertext != plaintext
        assert blob.key_id == "local-dev-kms"
        assert await kms.decrypt(blob) == plaintext

    @pytest.mark.asyncio
    async def test_round_trip_with_aad(self):
        kms = LocalDevKms()
        blob = await kms.encrypt(b"data", aad=b"tenant-123")
        assert await kms.decrypt(blob, aad=b"tenant-123") == b"data"

    @pytest.mark.asyncio
    async def test_wrong_aad_fails(self):
        kms = LocalDevKms()
        blob = await kms.encrypt(b"data", aad=b"tenant-123")
        with pytest.raises(Exception):
            await kms.decrypt(blob, aad=b"tenant-999")


# ---------------------------------------------------------------------------
# InMemoryObjectStore
# ---------------------------------------------------------------------------


class TestInMemoryObjectStore:
    @pytest.mark.asyncio
    async def test_put_get_delete(self):
        store = InMemoryObjectStore()
        uri = await store.put("a/b/c.txt", b"hello", content_type="text/plain")
        assert uri == "mem://a/b/c.txt"
        assert await store.get("a/b/c.txt") == b"hello"
        await store.delete("a/b/c.txt")
        with pytest.raises(FileNotFoundError):
            await store.get("a/b/c.txt")

    @pytest.mark.asyncio
    async def test_delete_prefix(self):
        store = InMemoryObjectStore()
        await store.put("t1/doc1/v1.txt", b"x")
        await store.put("t1/doc2/v1.txt", b"y")
        await store.put("t2/doc3/v1.txt", b"z")
        assert await store.delete_prefix("t1/") == 2
        assert await store.get("t2/doc3/v1.txt") == b"z"


# ---------------------------------------------------------------------------
# NullIdentityProvider + Principal
# ---------------------------------------------------------------------------


class TestIdentity:
    @pytest.mark.asyncio
    async def test_null_idp_rejects(self):
        idp = NullIdentityProvider()
        assert idp.kind == "none"
        with pytest.raises(IdentityError):
            await idp.verify_assertion("anything")

    def test_principal_roles(self):
        p = Principal(tenant_id="t", subject="u", roles=("analyst", "auditor"))
        assert p.has_role("analyst")
        assert not p.has_role("org_admin")


# ---------------------------------------------------------------------------
# Single-tenant enforcement middleware (Req 1.2)
# ---------------------------------------------------------------------------


class _FakeAuth:
    """Auth service that authenticates every request as a fixed tenant."""

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    async def authenticate(self, headers, **kwargs):  # noqa: ANN001, ANN003
        from backend.auth.service import AuthResult

        return AuthResult(tenant_id=self._tenant_id, api_key_id="k")


class TestSingleTenantEnforcement:
    def _build(self, *, configured_tenant: str, request_tenant: str):
        from backend.api_gateway.app import create_app
        from backend.config.settings import Settings

        settings = Settings(
            _env_file=None,
            deployment_mode=DeploymentMode.DEDICATED_VPC,
            dedicated_tenant_id=configured_tenant,
            secrets_backend="aws",
            kms_backend="aws",
            kms_key_id="arn:aws:kms:eu-west-1:111:key/abc",
        )
        # Build dev providers explicitly so no AWS calls happen during the test.
        from backend.providers.dev_providers import (
            EnvSecretsProvider,
            InMemoryObjectStore,
            LocalDevKms,
            NullIdentityProvider,
        )
        from backend.providers.interfaces import Providers

        providers = Providers(
            secrets=EnvSecretsProvider(),
            kms=LocalDevKms(),
            object_store=InMemoryObjectStore(),
            identity=NullIdentityProvider(),
        )
        return create_app(
            auth_service=_FakeAuth(request_tenant),
            settings=settings,
            providers=providers,
        )

    @pytest.mark.asyncio
    async def test_matching_tenant_allowed(self):
        from httpx import ASGITransport, AsyncClient

        app = self._build(configured_tenant="bank-123", request_tenant="bank-123")

        @app.get("/v1/probe")
        async def probe():  # noqa: ANN202
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": True})

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/probe", headers={"authorization": "Bearer x"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_foreign_tenant_returns_uniform_not_found(self):
        from httpx import ASGITransport, AsyncClient

        app = self._build(configured_tenant="bank-123", request_tenant="attacker-999")

        @app.get("/v1/probe")
        async def probe():  # noqa: ANN202
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": True})

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/probe", headers={"authorization": "Bearer x"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "resource_not_found"

    @pytest.mark.asyncio
    async def test_health_exempt_from_single_tenant(self):
        from httpx import ASGITransport, AsyncClient

        app = self._build(configured_tenant="bank-123", request_tenant="attacker-999")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
