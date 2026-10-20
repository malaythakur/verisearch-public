"""OIDC identity provider (Enterprise Hardening Phase 5, Req 4).

Validates OIDC ID tokens for human (SSO) authentication:
- Fetches and caches the issuer's JWKS (public signing keys).
- Verifies signature (RS256/ES256), issuer, audience, and expiry.
- Maps configured claims to a unified ``Principal`` (tenant, subject, roles).

This is the machine-to-human bridge: API-key auth (AuthService) is unchanged; this
provider is only used for browser/SSO sessions. Network calls (JWKS fetch) use a short
timeout and the result is cached with a TTL.
"""

from __future__ import annotations

import time
from typing import Any

from backend.providers.interfaces import IdentityError, IdentityProvider, Principal


class OidcIdentityProvider(IdentityProvider):
    """Validates OIDC ID tokens and maps them to a Principal."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        roles_claim: str = "roles",
        tenant_claim: str = "tenant_id",
        default_roles: tuple[str, ...] = (),
        tenant_from_subject: bool = False,
        jwks_ttl_seconds: int = 3600,
        http_timeout: float = 5.0,
    ) -> None:
        if not issuer:
            raise ValueError("oidc issuer is required")
        if not audience:
            raise ValueError("oidc audience is required")
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks_uri = jwks_uri or f"{self._issuer}/.well-known/jwks.json"
        self._roles_claim = roles_claim
        self._tenant_claim = tenant_claim
        self._default_roles = tuple(default_roles)
        self._tenant_from_subject = tenant_from_subject
        self._jwks_ttl = jwks_ttl_seconds
        self._http_timeout = http_timeout
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_expires_at: float = 0.0

    @property
    def kind(self) -> str:
        return "oidc"

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch the JWKS, using the TTL cache when fresh."""
        now = time.monotonic()
        if self._jwks_cache is not None and now < self._jwks_expires_at:
            return self._jwks_cache

        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.get(self._jwks_uri)
                resp.raise_for_status()
                jwks = resp.json()
        except Exception as e:  # noqa: BLE001
            raise IdentityError(f"failed to fetch JWKS from {self._jwks_uri}") from e

        self._jwks_cache = jwks
        self._jwks_expires_at = now + self._jwks_ttl
        return jwks

    def _set_jwks_for_test(self, jwks: dict[str, Any]) -> None:
        """Inject a JWKS document (test helper); avoids network in unit tests."""
        self._jwks_cache = jwks
        self._jwks_expires_at = time.monotonic() + self._jwks_ttl

    async def verify_assertion(self, token_or_assertion: str) -> Principal:
        """Validate an OIDC ID token and return a Principal.

        Raises:
            IdentityError: on missing/invalid/expired token or untrusted issuer.
        """
        import jwt
        from jwt import PyJWKClient, PyJWK  # noqa: F401  (PyJWK used indirectly)

        token = (token_or_assertion or "").strip()
        if not token:
            raise IdentityError("empty token")

        # Resolve the signing key for this token's kid from the JWKS.
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:  # noqa: BLE001
            raise IdentityError("malformed token header") from e

        kid = unverified_header.get("kid")
        jwks = await self._get_jwks()
        signing_key = self._select_key(jwks, kid)
        if signing_key is None:
            raise IdentityError("no matching signing key for token kid")

        try:
            from jwt.algorithms import RSAAlgorithm, ECAlgorithm

            alg = signing_key.get("kty")
            if alg == "RSA":
                key = RSAAlgorithm.from_jwk(_json(signing_key))
                algorithms = ["RS256", "RS384", "RS512"]
            elif alg == "EC":
                key = ECAlgorithm.from_jwk(_json(signing_key))
                algorithms = ["ES256", "ES384", "ES512"]
            else:
                raise IdentityError(f"unsupported key type: {alg}")

            claims = jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except IdentityError:
            raise
        except jwt.ExpiredSignatureError as e:
            raise IdentityError("token expired") from e
        except jwt.InvalidIssuerError as e:
            raise IdentityError("untrusted issuer") from e
        except jwt.InvalidAudienceError as e:
            raise IdentityError("invalid audience") from e
        except Exception as e:  # noqa: BLE001
            raise IdentityError("token validation failed") from e

        return self._principal_from_claims(claims)

    def _select_key(self, jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
        keys = jwks.get("keys", [])
        if not keys:
            return None
        if kid is None:
            return keys[0]
        for k in keys:
            if k.get("kid") == kid:
                return k
        return None

    def _principal_from_claims(self, claims: dict[str, Any]) -> Principal:
        subject = str(claims.get("sub", ""))
        if not subject:
            raise IdentityError("token missing subject")

        tenant_id = str(claims.get(self._tenant_claim, "") or "")
        # Consumer fallback: with no tenant claim, derive a private per-user
        # tenant from the subject so every signed-in user gets an isolated
        # corpus without any org/tenant configuration.
        if not tenant_id and self._tenant_from_subject:
            tenant_id = f"user:{subject}"

        raw_roles = claims.get(self._roles_claim, [])
        if isinstance(raw_roles, str):
            roles = tuple(r.strip() for r in raw_roles.split() if r.strip())
        elif isinstance(raw_roles, (list, tuple)):
            roles = tuple(str(r) for r in raw_roles)
        else:
            roles = ()
        # Grant default roles when the token carries none (consumer users have
        # no role claim configured in the IdP).
        if not roles and self._default_roles:
            roles = self._default_roles

        return Principal(
            tenant_id=tenant_id,
            subject=subject,
            roles=roles,
            auth_kind="human",
        )


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)
