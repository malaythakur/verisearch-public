"""Application settings loaded from environment variables using Pydantic v2 BaseSettings."""

from enum import Enum
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class AppEnvironment(str, Enum):
    """Application deployment environment."""

    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class DeploymentMode(str, Enum):
    """Deployment topology selected by configuration (Enterprise Hardening Req 1).

    - POOLED: operator-hosted, multi-tenant (tenant_id isolates customers).
    - DEDICATED_VPC: single-tenant, dedicated VPC in the operator's account.
    - CUSTOMER_MANAGED: single-tenant, deployed into the customer's own account.
    """

    POOLED = "pooled"
    DEDICATED_VPC = "dedicated_vpc"
    CUSTOMER_MANAGED = "customer_managed"


class Settings(BaseSettings):
    """Main application settings sourced from environment variables.

    All settings can be overridden via environment variables.
    Defaults are tuned for local development with Docker Compose.
    """

    # --- PostgreSQL ---
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="agentic_research", description="PostgreSQL database name")
    postgres_user: str = Field(default="agentic", description="PostgreSQL user")
    postgres_password: str = Field(default="agentic_dev", description="PostgreSQL password")
    database_url: str = Field(
        default="postgresql://agentic:agentic_dev@localhost:5432/agentic_research",
        description="Full PostgreSQL connection URL",
    )

    # --- OpenSearch ---
    opensearch_url: str = Field(default="http://localhost:9200", description="OpenSearch cluster URL")

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # --- Kafka ---
    kafka_bootstrap_servers: str = Field(
        default="localhost:19092", description="Kafka bootstrap servers (comma-separated)"
    )

    # --- S3-compatible object store ---
    aws_endpoint_url: str = Field(default="http://localhost:9000", description="S3-compatible endpoint URL")
    s3_bucket: str = Field(default="agentic-research-docs", description="S3 bucket for document storage")
    aws_access_key_id: str = Field(default="minioadmin", description="AWS/S3 access key ID")
    aws_secret_access_key: str = Field(default="minioadmin", description="AWS/S3 secret access key")
    aws_default_region: str = Field(default="us-east-1", description="AWS/S3 default region")

    # --- Application ---
    app_env: AppEnvironment = Field(default=AppEnvironment.DEV, description="Application environment")
    log_level: str = Field(default="INFO", description="Logging level")
    service_name: str = Field(default="agentic-research", description="Service name for observability")

    # --- Deployment mode & provider selection (Enterprise Hardening Req 1) ---
    deployment_mode: DeploymentMode = Field(
        default=DeploymentMode.POOLED, description="Deployment topology"
    )
    dedicated_tenant_id: str | None = Field(
        default=None,
        description="The single tenant served in dedicated_vpc/customer_managed modes",
    )
    data_residency_region: str = Field(
        default="eu-west-1", description="AWS region a tenant's data is pinned to"
    )
    secrets_backend: Literal["env", "aws"] = Field(
        default="env", description="Secrets provider implementation"
    )
    kms_backend: Literal["local", "aws"] = Field(
        default="local", description="KMS/encryption provider implementation"
    )
    kms_key_id: str | None = Field(
        default=None, description="KMS key id/ARN (required when kms_backend=aws)"
    )
    object_store_backend: Literal["minio", "s3"] = Field(
        default="minio", description="Object store implementation"
    )
    idp_kind: Literal["none", "oidc", "saml"] = Field(
        default="none", description="Human-identity provider kind"
    )
    # OIDC settings (used when idp_kind='oidc'; Phase 5)
    oidc_issuer: str | None = Field(default=None, description="OIDC issuer URL")
    oidc_audience: str | None = Field(default=None, description="OIDC audience (client id)")
    oidc_jwks_uri: str | None = Field(
        default=None, description="OIDC JWKS URI (derived from issuer if omitted)"
    )
    oidc_roles_claim: str = Field(
        default="roles", description="JWT claim containing the user's roles/groups"
    )
    oidc_tenant_claim: str = Field(
        default="tenant_id", description="JWT claim containing the tenant id"
    )
    oidc_default_roles: str = Field(
        default="analyst",
        description=(
            "Comma-separated roles granted to OIDC users when the token carries "
            "no roles claim. For a consumer (e.g. Clerk + Google) deployment this "
            "is typically 'analyst' so signed-in users can search/answer/index "
            "but not access admin/audit."
        ),
    )
    oidc_tenant_from_subject: bool = Field(
        default=False,
        description=(
            "When True and the token has no tenant claim, derive a per-user "
            "tenant_id from the subject ('user:<sub>'). Gives every signed-in "
            "consumer a private corpus without org configuration."
        ),
    )
    sso_required: bool = Field(
        default=False, description="When True, only SSO is accepted (no API-key fallback)"
    )
    telemetry_sink: str | None = Field(
        default=None, description="Telemetry destination (customer-controlled in dedicated/customer modes)"
    )

    # --- Secret names/ARNs (used when secrets_backend='aws'; Phase 1, Req 2.2) ---
    # In production the application carries secret *names*, not values. The actual
    # values are fetched from the SecretsProvider at startup.
    database_url_secret_name: str | None = Field(
        default=None, description="Secrets Manager name/ARN for DATABASE_URL"
    )
    openai_api_key_secret_name: str | None = Field(
        default=None, description="Secrets Manager name/ARN for OPENAI_API_KEY"
    )
    anthropic_api_key_secret_name: str | None = Field(
        default=None, description="Secrets Manager name/ARN for ANTHROPIC_API_KEY"
    )
    aws_secret_access_key_secret_name: str | None = Field(
        default=None, description="Secrets Manager name/ARN for AWS_SECRET_ACCESS_KEY"
    )
    audit_signing_key_secret_name: str | None = Field(
        default=None, description="Secrets Manager name/ARN for the audit hash-chain signing key"
    )

    # --- Connection pool (Phase 4, Req 8.3) ---
    db_pool_min_size: int = Field(default=2, description="asyncpg pool minimum size")
    db_pool_max_size: int = Field(default=10, description="asyncpg pool maximum size")
    db_command_timeout: int = Field(default=30, description="asyncpg command timeout (seconds)")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def is_single_tenant(self) -> bool:
        """True when the deployment serves exactly one tenant."""
        return self.deployment_mode in (
            DeploymentMode.DEDICATED_VPC,
            DeploymentMode.CUSTOMER_MANAGED,
        )

    def validate_for_mode(self) -> None:
        """Fail-fast validation of mode-required configuration (Req 1.5, 2.5).

        Raises:
            ConfigurationError: listing every missing/invalid key for the mode.
        """
        missing: list[str] = []

        if self.is_single_tenant():
            if not self.dedicated_tenant_id:
                missing.append("dedicated_tenant_id (required for single-tenant modes)")

        if self.deployment_mode in (
            DeploymentMode.DEDICATED_VPC,
            DeploymentMode.CUSTOMER_MANAGED,
        ):
            if self.secrets_backend != "aws":
                missing.append("secrets_backend must be 'aws' for dedicated/customer modes")
            if self.kms_backend != "aws":
                missing.append("kms_backend must be 'aws' for dedicated/customer modes")

        if self.kms_backend == "aws" and not self.kms_key_id:
            missing.append("kms_key_id (required when kms_backend='aws')")

        if self.idp_kind == "oidc":
            if not self.oidc_issuer:
                missing.append("oidc_issuer (required when idp_kind='oidc')")
            if not self.oidc_audience:
                missing.append("oidc_audience (required when idp_kind='oidc')")

        if missing:
            raise ConfigurationError(
                "Invalid configuration for deployment_mode="
                f"'{self.deployment_mode.value}':\n  - " + "\n  - ".join(missing)
            )


class ConfigurationError(RuntimeError):
    """Raised on fail-fast startup when required configuration is missing/invalid."""
