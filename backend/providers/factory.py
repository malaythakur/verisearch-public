"""Provider selection factory.

Chooses concrete provider implementations from ``Settings`` at startup. Dev/no-op
implementations are always importable; AWS implementations are imported lazily so that
local development and tests do not require boto3 or AWS credentials.
"""

from __future__ import annotations

from backend.config.settings import Settings
from backend.providers.dev_providers import (
    EnvSecretsProvider,
    InMemoryObjectStore,
    LocalDevKms,
    NullIdentityProvider,
)
from backend.providers.interfaces import (
    IdentityProvider,
    KmsProvider,
    ObjectStore,
    Providers,
    SecretsProvider,
)


def _build_secrets(settings: Settings) -> SecretsProvider:
    if settings.secrets_backend == "aws":
        from backend.providers.aws_providers import AwsSecretsManagerProvider

        return AwsSecretsManagerProvider(region=settings.data_residency_region)
    return EnvSecretsProvider()


def _build_kms(settings: Settings) -> KmsProvider:
    if settings.kms_backend == "aws":
        from backend.providers.aws_providers import AwsKmsProvider

        assert settings.kms_key_id, "kms_key_id required for aws kms backend"
        return AwsKmsProvider(key_id=settings.kms_key_id, region=settings.data_residency_region)
    return LocalDevKms()


def _build_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "s3":
        from backend.providers.aws_providers import S3ObjectStore

        return S3ObjectStore(
            bucket=settings.s3_bucket,
            region=settings.data_residency_region,
            endpoint_url=settings.aws_endpoint_url or None,
        )
    return InMemoryObjectStore()


def _build_identity(settings: Settings) -> IdentityProvider | None:
    if settings.idp_kind == "none":
        return NullIdentityProvider()
    # OIDC/SAML providers are implemented in Phase 5; until then, selecting them is a
    # configuration error surfaced at startup rather than a silent fallback.
    from backend.providers.aws_providers import build_identity_provider

    return build_identity_provider(settings)


def build_providers(settings: Settings) -> Providers:
    """Construct the provider bundle for the given settings."""
    return Providers(
        secrets=_build_secrets(settings),
        kms=_build_kms(settings),
        object_store=_build_object_store(settings),
        identity=_build_identity(settings),
    )
