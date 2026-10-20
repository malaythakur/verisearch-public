"""Tests for Enterprise Hardening Phase 1: secrets management + log redaction."""

import logging
import os
from unittest.mock import patch

import pytest

from backend.config.settings import Settings
from backend.providers.interfaces import SecretNotFoundError, SecretsProvider
from backend.providers.secret_resolution import (
    SecretResolutionError,
    collect_resolved_secret_values,
    resolve_secrets,
)
from backend.providers.log_redaction import (
    SecretRedactionFilter,
    clear_registered_secrets,
    register_secret_values,
    scrub_secrets,
)


# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------


class _FakeSecrets(SecretsProvider):
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self.calls: list[str] = []

    async def get_secret(self, name: str) -> str:
        self.calls.append(name)
        if name not in self._store:
            raise SecretNotFoundError(name)
        return self._store[name]

    async def get_secret_json(self, name: str) -> dict:
        import json

        return json.loads(await self.get_secret(name))


# ---------------------------------------------------------------------------
# resolve_secrets (Req 2.2, 2.5)
# ---------------------------------------------------------------------------


class TestResolveSecrets:
    @pytest.mark.asyncio
    async def test_dev_backend_uses_environment(self):
        s = Settings(_env_file=None, secrets_backend="env")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key-123456"}, clear=False):
            provider = _FakeSecrets({})
            resolved = await resolve_secrets(s, provider)
            assert resolved.get("OPENAI_API_KEY") == "env-key-123456"
            # Dev backend should not call the provider.
            assert provider.calls == []

    @pytest.mark.asyncio
    async def test_aws_backend_fetches_by_name_and_injects_env(self):
        s = Settings(
            _env_file=None,
            secrets_backend="aws",
            database_url_secret_name="prod/db-url",
            openai_api_key_secret_name="prod/openai",
        )
        provider = _FakeSecrets(
            {
                "prod/db-url": "postgresql://u:p@host/db",
                "prod/openai": "gsk_live_value_abcdef123456",
            }
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            resolved = await resolve_secrets(s, provider)
            assert resolved["DATABASE_URL"] == "postgresql://u:p@host/db"
            assert os.environ["DATABASE_URL"] == "postgresql://u:p@host/db"
            assert resolved["OPENAI_API_KEY"] == "gsk_live_value_abcdef123456"

    @pytest.mark.asyncio
    async def test_required_secret_missing_fails_fast(self):
        s = Settings(
            _env_file=None,
            secrets_backend="aws",
            database_url_secret_name="prod/db-url",
        )
        provider = _FakeSecrets({})  # db-url not present -> required, must raise
        with pytest.raises(SecretResolutionError):
            await resolve_secrets(s, provider)

    @pytest.mark.asyncio
    async def test_required_secret_without_name_fails_fast(self):
        # aws backend but no database_url_secret_name configured -> fail fast
        s = Settings(_env_file=None, secrets_backend="aws")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            provider = _FakeSecrets({})
            with pytest.raises(SecretResolutionError):
                await resolve_secrets(s, provider)

    @pytest.mark.asyncio
    async def test_optional_secret_missing_is_skipped(self):
        s = Settings(
            _env_file=None,
            secrets_backend="aws",
            database_url_secret_name="prod/db-url",
            openai_api_key_secret_name="prod/openai-missing",
        )
        provider = _FakeSecrets({"prod/db-url": "postgresql://u:p@host/db"})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            resolved = await resolve_secrets(s, provider)
            assert "OPENAI_API_KEY" not in resolved  # optional, skipped


# ---------------------------------------------------------------------------
# Secret redaction (Req 2.6)
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    def test_registered_value_is_scrubbed(self):
        register_secret_values({"super-secret-db-password"})
        out = scrub_secrets("connecting with super-secret-db-password to db")
        assert "super-secret-db-password" not in out
        assert "[REDACTED_SECRET]" in out

    def test_openai_style_key_pattern_scrubbed(self):
        out = scrub_secrets("key=gsk_ABCDEFGHIJKLMNOPQRSTUVWX failed")
        assert "gsk_ABCDEFGHIJKLMNOPQRSTUVWX" not in out
        assert "[REDACTED_SECRET]" in out

    def test_aws_access_key_pattern_scrubbed(self):
        out = scrub_secrets("AKIAIOSFODNN7EXAMPLE in trace")
        assert "AKIAIOSFODNN7EXAMPLE" not in out

    def test_bearer_token_scrubbed(self):
        out = scrub_secrets("Authorization: Bearer abcdef1234567890ABCDEF")
        assert "abcdef1234567890ABCDEF" not in out

    def test_non_secret_text_untouched(self):
        assert scrub_secrets("a normal log line") == "a normal log line"

    def test_filter_scrubs_log_record_message(self):
        register_secret_values({"my-leaked-secret-value"})
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname="", lineno=0,
            msg="leaked my-leaked-secret-value here", args=(), exc_info=None,
        )
        assert f.filter(record) is True
        assert "my-leaked-secret-value" not in record.getMessage()

    def test_filter_scrubs_exc_text(self):
        register_secret_values({"trace-secret-xyz123"})
        f = SecretRedactionFilter()
        record = logging.LogRecord(
            name="t", level=logging.ERROR, pathname="", lineno=0,
            msg="boom", args=(), exc_info=None,
        )
        record.exc_text = "Traceback ... token=trace-secret-xyz123 ..."
        f.filter(record)
        assert "trace-secret-xyz123" not in record.exc_text


# ---------------------------------------------------------------------------
# collect_resolved_secret_values
# ---------------------------------------------------------------------------


class TestCollectSecretValues:
    def test_collects_present_env_secrets(self):
        env = {
            "DATABASE_URL": "postgresql://u:p@h/db",
            "OPENAI_API_KEY": "gsk_value_123456",
            "UNRELATED": "ignored",
        }
        values = collect_resolved_secret_values(env)
        assert "postgresql://u:p@h/db" in values
        assert "gsk_value_123456" in values
        assert "ignored" not in values
