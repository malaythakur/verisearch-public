"""Runtime secret resolution (Enterprise Hardening Phase 1, Req 2).

At startup the application resolves its runtime secrets through the configured
``SecretsProvider`` rather than reading raw values from the environment. In production
(``secrets_backend='aws'``) ``Settings`` carries secret *names/ARNs* and the actual
values come from AWS Secrets Manager; in dev (``secrets_backend='env'``) the values are
read directly from the environment via ``EnvSecretsProvider``.

Resolved secrets are placed into ``os.environ`` so existing call sites (which read
``os.environ["OPENAI_API_KEY"]`` etc.) keep working unchanged — the difference is that
the values now originate from the provider and a required-but-missing secret fails fast
(Req 2.5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.config.settings import Settings
from backend.providers.interfaces import SecretNotFoundError, SecretsProvider


@dataclass(frozen=True, slots=True)
class SecretSpec:
    """Describes a runtime secret to resolve.

    Attributes:
        env_var: The environment variable the application reads at runtime.
        name_setting: The Settings field holding the secret *name/ARN* (prod), if any.
        required_in_prod: Whether the secret must resolve in non-dev secrets backends.
    """

    env_var: str
    name_setting: str | None = None
    required_in_prod: bool = False


# The runtime secrets the platform depends on. ``required_in_prod`` marks the secrets
# without which the service must not start when using a real secrets backend.
SECRET_SPECS: tuple[SecretSpec, ...] = (
    SecretSpec("DATABASE_URL", name_setting="database_url_secret_name", required_in_prod=True),
    SecretSpec("OPENAI_API_KEY", name_setting="openai_api_key_secret_name", required_in_prod=False),
    SecretSpec("ANTHROPIC_API_KEY", name_setting="anthropic_api_key_secret_name", required_in_prod=False),
    SecretSpec("AWS_SECRET_ACCESS_KEY", name_setting="aws_secret_access_key_secret_name", required_in_prod=False),
    SecretSpec("AUDIT_SIGNING_KEY", name_setting="audit_signing_key_secret_name", required_in_prod=False),
)


class SecretResolutionError(RuntimeError):
    """Raised when a required secret cannot be resolved at startup (Req 2.5)."""


def collect_resolved_secret_values(env: dict[str, str] | None = None) -> set[str]:
    """Return the set of currently-known secret values for log redaction.

    Reads the env vars named in ``SECRET_SPECS`` plus any value already present.
    Used to seed the :class:`SecretRedactionFilter`.
    """
    source = env if env is not None else os.environ
    values: set[str] = set()
    for spec in SECRET_SPECS:
        v = source.get(spec.env_var)
        if v:
            values.add(v)
    return values


async def resolve_secrets(
    settings: Settings,
    provider: SecretsProvider,
) -> dict[str, str]:
    """Resolve runtime secrets via the provider and inject them into os.environ.

    For each spec:
    - In dev (env backend): the value is already in the environment; we keep it.
    - In prod (aws backend): if the corresponding ``*_secret_name`` setting is set,
      fetch the value by that name and inject it into ``os.environ[env_var]``.

    Returns a mapping of resolved env_var -> value (for redaction seeding).

    Raises:
        SecretResolutionError: if a required-in-prod secret cannot be resolved.
    """
    resolved: dict[str, str] = {}
    is_prod_backend = settings.secrets_backend == "aws"

    for spec in SECRET_SPECS:
        # Determine the secret name to fetch (prod) — falls back to None in dev.
        secret_name = (
            getattr(settings, spec.name_setting, None) if spec.name_setting else None
        )

        if is_prod_backend and secret_name:
            try:
                value = await provider.get_secret(secret_name)
            except SecretNotFoundError as e:
                if spec.required_in_prod:
                    raise SecretResolutionError(
                        f"required secret '{spec.env_var}' (name='{secret_name}') "
                        f"could not be resolved at startup"
                    ) from e
                continue
            os.environ[spec.env_var] = value
            resolved[spec.env_var] = value
            continue

        # Dev backend (or no name configured): value comes from the environment.
        existing = os.environ.get(spec.env_var)
        if existing:
            resolved[spec.env_var] = existing
        elif is_prod_backend and spec.required_in_prod and not secret_name:
            raise SecretResolutionError(
                f"required secret '{spec.env_var}' has no configured "
                f"'{spec.name_setting}' for the aws secrets backend"
            )

    return resolved
