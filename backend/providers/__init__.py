"""Platform provider abstraction layer (Enterprise Hardening Phase 0).

Defines the provider interfaces (Protocols) that application code depends on, plus a
``Providers`` container and a ``build_providers()`` factory that selects concrete
implementations from ``Settings`` at startup. Application/service code MUST depend only
on these interfaces, never on a concrete provider — this is what lets one codebase run
in pooled, dedicated-VPC, and customer-managed deployment modes without forking.
"""

from backend.providers.interfaces import (
    IdentityProvider,
    KmsProvider,
    ObjectStore,
    Principal,
    Providers,
    SecretsProvider,
)
from backend.providers.factory import build_providers
from backend.providers.content_encryption import (
    ContentEncryptor,
    deserialize_blob,
    is_encrypted,
    serialize_blob,
)
from backend.providers.secret_resolution import (
    SECRET_SPECS,
    SecretResolutionError,
    SecretSpec,
    collect_resolved_secret_values,
    resolve_secrets,
)

__all__ = [
    "IdentityProvider",
    "KmsProvider",
    "ObjectStore",
    "Principal",
    "Providers",
    "SecretsProvider",
    "build_providers",
    "ContentEncryptor",
    "deserialize_blob",
    "is_encrypted",
    "serialize_blob",
    "SECRET_SPECS",
    "SecretResolutionError",
    "SecretSpec",
    "collect_resolved_secret_values",
    "resolve_secrets",
]
