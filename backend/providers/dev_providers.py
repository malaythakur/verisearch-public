"""Development / no-op provider implementations.

These keep local development and tests working with no AWS account:
- ``EnvSecretsProvider``  — reads secrets from environment variables.
- ``LocalDevKms``         — AES-GCM envelope encryption with a local static key.
- ``InMemoryObjectStore`` — process-local blob storage (tests/dev).
- ``NullIdentityProvider``— no human SSO configured.

AWS implementations live in ``aws_providers.py`` and share these interfaces.
"""

from __future__ import annotations

import hashlib
import json
import os

from backend.providers.interfaces import (
    EncryptedBlob,
    IdentityError,
    IdentityProvider,
    KmsProvider,
    ObjectStore,
    Principal,
    SecretNotFoundError,
    SecretsProvider,
)


class EnvSecretsProvider(SecretsProvider):
    """Resolves secrets from environment variables (dev / pooled bootstrap)."""

    def __init__(self, *, prefix: str = "") -> None:
        self._prefix = prefix

    async def get_secret(self, name: str) -> str:
        value = os.environ.get(self._prefix + name)
        if value is None:
            raise SecretNotFoundError(f"secret '{name}' not set in environment")
        return value

    async def get_secret_json(self, name: str) -> dict:
        raw = await self.get_secret(name)
        return json.loads(raw)


class LocalDevKms(KmsProvider):
    """Local AES-GCM envelope encryption for dev/tests (NOT for production).

    The master key is derived from a static seed so encryption is deterministic and
    self-contained. Mirrors the envelope shape used by the AWS provider.
    """

    _KEY_ID = "local-dev-kms"

    def __init__(self, seed: str = "local-dev-master-key") -> None:
        # 32-byte master key derived from the seed.
        self._master_key = hashlib.sha256(seed.encode("utf-8")).digest()

    @property
    def key_id(self) -> str:
        return self._KEY_ID

    async def encrypt(self, plaintext: bytes, *, aad: bytes | None = None) -> EncryptedBlob:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # Generate a per-message data key, encrypt data with it, then wrap the data
        # key under the master key (envelope encryption).
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, aad)

        wrap_nonce = os.urandom(12)
        wrapped = AESGCM(self._master_key).encrypt(wrap_nonce, data_key, None)
        return EncryptedBlob(
            ciphertext=ciphertext,
            wrapped_data_key=wrap_nonce + wrapped,
            key_id=self._KEY_ID,
            nonce=nonce,
        )

    async def decrypt(self, blob: EncryptedBlob, *, aad: bytes | None = None) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        wrap_nonce, wrapped = blob.wrapped_data_key[:12], blob.wrapped_data_key[12:]
        data_key = AESGCM(self._master_key).decrypt(wrap_nonce, wrapped, None)
        return AESGCM(data_key).decrypt(blob.nonce, blob.ciphertext, aad)


class InMemoryObjectStore(ObjectStore):
    """Process-local object store for dev/tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        self._store[key] = data
        return f"mem://{key}"

    async def get(self, key: str) -> bytes:
        if key not in self._store:
            raise FileNotFoundError(f"object not found: {key}")
        return self._store[key]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)


class NullIdentityProvider(IdentityProvider):
    """No human SSO configured. Any assertion is rejected."""

    @property
    def kind(self) -> str:
        return "none"

    async def verify_assertion(self, token_or_assertion: str) -> Principal:
        raise IdentityError("no identity provider configured for this deployment")
