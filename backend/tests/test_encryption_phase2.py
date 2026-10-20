"""Tests for Enterprise Hardening Phase 2: encryption + security middleware."""

import pytest

from backend.providers.content_encryption import (
    ContentEncryptor,
    deserialize_blob,
    is_encrypted,
    serialize_blob,
)
from backend.providers.dev_providers import LocalDevKms


# ---------------------------------------------------------------------------
# Content encryption round-trip (Req 3.4)
# ---------------------------------------------------------------------------


class TestContentEncryptor:
    @pytest.mark.asyncio
    async def test_round_trip(self):
        enc = ContentEncryptor(LocalDevKms())
        plaintext = "Sensitive document content with PII a@b.com"
        stored = await enc.encrypt_text(plaintext)
        assert is_encrypted(stored)
        assert plaintext not in stored  # ciphertext, not plaintext
        assert await enc.decrypt_text(stored) == plaintext

    @pytest.mark.asyncio
    async def test_round_trip_with_tenant_aad(self):
        enc = ContentEncryptor(LocalDevKms())
        stored = await enc.encrypt_text("data", tenant_id="bank-123")
        assert await enc.decrypt_text(stored, tenant_id="bank-123") == "data"

    @pytest.mark.asyncio
    async def test_wrong_tenant_aad_fails(self):
        enc = ContentEncryptor(LocalDevKms())
        stored = await enc.encrypt_text("data", tenant_id="bank-123")
        with pytest.raises(Exception):
            await enc.decrypt_text(stored, tenant_id="attacker-999")

    @pytest.mark.asyncio
    async def test_plaintext_passthrough_on_decrypt(self):
        enc = ContentEncryptor(LocalDevKms())
        # A non-enc:v1 value is returned unchanged (backward compatibility).
        assert await enc.decrypt_text("just plaintext") == "just plaintext"

    @pytest.mark.asyncio
    async def test_serialize_deserialize(self):
        kms = LocalDevKms()
        blob = await kms.encrypt(b"hello")
        text = serialize_blob(blob)
        assert text.startswith("enc:v1:")
        back = deserialize_blob(text)
        assert back.ciphertext == blob.ciphertext
        assert back.key_id == blob.key_id
        assert back.nonce == blob.nonce
        assert back.wrapped_data_key == blob.wrapped_data_key

    def test_is_encrypted(self):
        assert is_encrypted("enc:v1:abc.def.ghi.jkl")
        assert not is_encrypted("plain text")
        assert not is_encrypted("")

    def test_deserialize_rejects_plaintext(self):
        with pytest.raises(ValueError):
            deserialize_blob("not encrypted")

    def test_deserialize_rejects_malformed(self):
        with pytest.raises(ValueError):
            deserialize_blob("enc:v1:onlyonepart")


# ---------------------------------------------------------------------------
# Security middleware (Req 3.1, 14.7)
# ---------------------------------------------------------------------------


def _build_app(*, https_only: bool):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from backend.api_gateway.middleware.security import SecurityMiddleware

    app = FastAPI()
    app.add_middleware(SecurityMiddleware, https_only=https_only, hsts=True)

    @app.get("/v1/probe")
    async def probe():  # noqa: ANN202
        return JSONResponse({"ok": True})

    @app.get("/health")
    async def health():  # noqa: ANN202
        return JSONResponse({"status": "healthy"})

    return app


class TestSecurityMiddleware:
    @pytest.mark.asyncio
    async def test_security_headers_present(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(https_only=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/probe")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in resp.headers
        assert "strict-transport-security" in resp.headers

    @pytest.mark.asyncio
    async def test_https_only_rejects_plain_http(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(https_only=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/probe")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "https_required"

    @pytest.mark.asyncio
    async def test_https_only_allows_forwarded_https(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(https_only=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/probe", headers={"x-forwarded-proto": "https"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_https_only_exempts_health(self):
        from httpx import ASGITransport, AsyncClient

        app = _build_app(https_only=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
