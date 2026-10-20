"""AWS provider implementations.

boto3 is imported lazily inside methods so that importing this module never forces a
boto3 dependency in environments that don't use the AWS backends. These are exercised
in pooled/dedicated/customer-managed deployments; dev/tests use the dev providers.
"""

from __future__ import annotations

import json
import time

from backend.providers.interfaces import (
    EncryptedBlob,
    IdentityProvider,
    KmsProvider,
    ObjectStore,
    SecretNotFoundError,
    SecretsProvider,
)


class AwsSecretsManagerProvider(SecretsProvider):
    """Resolves secrets from AWS Secrets Manager with a TTL cache (rotation, Req 2.4)."""

    def __init__(self, *, region: str, ttl_seconds: int = 300) -> None:
        self._region = region
        self._ttl = ttl_seconds
        self._client = None
        self._cache: dict[str, tuple[str, float]] = {}

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    async def get_secret(self, name: str) -> str:
        now = time.monotonic()
        cached = self._cache.get(name)
        if cached is not None and now < cached[1]:
            return cached[0]

        try:
            resp = self._get_client().get_secret_value(SecretId=name)
        except Exception as e:  # noqa: BLE001 - normalize to a domain error
            raise SecretNotFoundError(f"secret '{name}' could not be resolved") from e

        value = resp.get("SecretString")
        if value is None:
            raise SecretNotFoundError(f"secret '{name}' has no string value")
        self._cache[name] = (value, now + self._ttl)
        return value

    async def get_secret_json(self, name: str) -> dict:
        return json.loads(await self.get_secret(name))


class AwsKmsProvider(KmsProvider):
    """Envelope encryption using AWS KMS GenerateDataKey + local AES-GCM."""

    def __init__(self, *, key_id: str, region: str) -> None:
        self._key_id = key_id
        self._region = region
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("kms", region_name=self._region)
        return self._client

    @property
    def key_id(self) -> str:
        return self._key_id

    async def encrypt(self, plaintext: bytes, *, aad: bytes | None = None) -> EncryptedBlob:
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        resp = self._get_client().generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
        plaintext_key = resp["Plaintext"]
        wrapped_key = resp["CiphertextBlob"]

        nonce = os.urandom(12)
        ciphertext = AESGCM(plaintext_key).encrypt(nonce, plaintext, aad)
        return EncryptedBlob(
            ciphertext=ciphertext,
            wrapped_data_key=wrapped_key,
            key_id=self._key_id,
            nonce=nonce,
        )

    async def decrypt(self, blob: EncryptedBlob, *, aad: bytes | None = None) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        resp = self._get_client().decrypt(
            CiphertextBlob=blob.wrapped_data_key, KeyId=self._key_id
        )
        plaintext_key = resp["Plaintext"]
        return AESGCM(plaintext_key).decrypt(blob.nonce, blob.ciphertext, aad)


class S3ObjectStore(ObjectStore):
    """S3-backed object store (also supports S3-compatible endpoints like MinIO)."""

    def __init__(self, *, bucket: str, region: str, endpoint_url: str | None = None) -> None:
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3", region_name=self._region, endpoint_url=self._endpoint_url
            )
        return self._client

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        kwargs = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self._get_client().put_object(**kwargs)
        return f"s3://{self._bucket}/{key}"

    async def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            resp = self._get_client().get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"object not found: {key}") from e
            raise

    async def delete(self, key: str) -> None:
        self._get_client().delete_object(Bucket=self._bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> int:
        client = self._get_client()
        deleted = 0
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            contents = page.get("Contents", [])
            if not contents:
                continue
            client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in contents], "Quiet": True},
            )
            deleted += len(contents)
        return deleted


def build_identity_provider(settings) -> IdentityProvider:  # noqa: ANN001
    """Construct an OIDC/SAML identity provider from settings (Phase 5).

    OIDC is fully implemented. SAML requires native XML-signature verification
    (xmlsec) which is intentionally not yet pulled in; selecting it fails closed
    with a clear message rather than pretending to validate.
    """
    kind = settings.idp_kind
    if kind == "oidc":
        from backend.providers.oidc_provider import OidcIdentityProvider

        return OidcIdentityProvider(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_uri=settings.oidc_jwks_uri,
            roles_claim=settings.oidc_roles_claim,
            tenant_claim=settings.oidc_tenant_claim,
            default_roles=tuple(
                r.strip() for r in (settings.oidc_default_roles or "").split(",") if r.strip()
            ),
            tenant_from_subject=bool(getattr(settings, "oidc_tenant_from_subject", False)),
        )
    if kind == "saml":
        raise NotImplementedError(
            "idp_kind='saml' requires XML-signature verification (xmlsec) which is "
            "not yet integrated. Use idp_kind='oidc' (most enterprise IdPs support "
            "OIDC) until SAML lands."
        )
    raise NotImplementedError(f"unsupported idp_kind: {kind}")
