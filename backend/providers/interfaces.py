"""Provider interfaces (Protocols) for the platform abstraction layer.

These define the contracts that application code depends on. Concrete implementations
(dev/no-op and AWS) live in sibling modules and are selected by ``build_providers()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@runtime_checkable
class SecretsProvider(Protocol):
    """Retrieves secret values by name. Implementations MUST NOT log secret values."""

    async def get_secret(self, name: str) -> str:
        """Return the secret value for ``name``.

        Raises:
            SecretNotFoundError: if the secret cannot be resolved.
        """
        ...

    async def get_secret_json(self, name: str) -> dict:
        """Return a JSON-decoded secret value for ``name``."""
        ...


class SecretNotFoundError(RuntimeError):
    """Raised when a required secret cannot be resolved."""


# ---------------------------------------------------------------------------
# KMS / envelope encryption
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EncryptedBlob:
    """Application-layer envelope-encrypted payload (Req 3.4)."""

    ciphertext: bytes
    wrapped_data_key: bytes
    key_id: str
    nonce: bytes


@runtime_checkable
class KmsProvider(Protocol):
    """Envelope encryption over a KMS-managed key."""

    @property
    def key_id(self) -> str:
        """The key identifier this provider encrypts under."""
        ...

    async def encrypt(self, plaintext: bytes, *, aad: bytes | None = None) -> EncryptedBlob:
        """Envelope-encrypt ``plaintext``; returns ciphertext + wrapped data key."""
        ...

    async def decrypt(self, blob: EncryptedBlob, *, aad: bytes | None = None) -> bytes:
        """Decrypt an :class:`EncryptedBlob` back to plaintext."""
        ...


# ---------------------------------------------------------------------------
# Object store
# ---------------------------------------------------------------------------


@runtime_checkable
class ObjectStore(Protocol):
    """Blob storage abstraction (S3 in prod, MinIO in dev)."""

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        """Store ``data`` at ``key``; returns a storage URI."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve the bytes stored at ``key``.

        Raises:
            FileNotFoundError: if no object exists at ``key``.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete the object at ``key`` (no error if absent)."""
        ...

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under ``prefix``; returns the count deleted."""
        ...


# ---------------------------------------------------------------------------
# Human identity (SSO)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """Unified authenticated principal across SSO and API-key auth planes.

    ``auth_kind`` is ``"human"`` for SSO-authenticated users and ``"machine"`` for
    API-key clients.
    """

    tenant_id: str
    subject: str
    roles: tuple[str, ...] = ()
    auth_kind: str = "machine"

    def has_role(self, role: str) -> bool:
        return role in self.roles


@runtime_checkable
class IdentityProvider(Protocol):
    """Validates human-identity assertions (OIDC/SAML) into a :class:`Principal`."""

    @property
    def kind(self) -> str:
        """One of ``none``, ``oidc``, ``saml``."""
        ...

    async def verify_assertion(self, token_or_assertion: str) -> Principal:
        """Validate an OIDC token / SAML assertion and return a Principal.

        Raises:
            IdentityError: if the assertion is missing, invalid, expired, or from an
                untrusted issuer.
        """
        ...


class IdentityError(RuntimeError):
    """Raised on invalid/expired/untrusted identity assertions."""


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Providers:
    """Bundle of platform providers selected at startup."""

    secrets: SecretsProvider
    kms: KmsProvider
    object_store: ObjectStore
    identity: IdentityProvider | None = None
    extras: dict = field(default_factory=dict)
