# Requirements Document

Enterprise Hardening (Bank-Grade)

## Introduction

This spec hardens the existing Agentic Research Search Engine into a product that
can pass the security, architecture, and procurement review of a Tier-1 financial
institution (the "JPMorgan standard"), while remaining sellable to smaller
financial-services buyers (fintechs, RIAs, regtech/compliance consultancies) in the
US and EU.

The product is positioned as **verifiable, auditable evidence retrieval**: every
answer is traceable to an exact source span, every source is trust-scored, and every
privileged action is recorded in a tamper-evident audit log. It is explicitly **not**
a decision-making or advisory system — it assembles and cites evidence; humans decide.

### Deployment Models

The same codebase and container image MUST support two deployment topologies,
selected by configuration only (no code forks):

- **Mode A — Pooled SaaS (multi-tenant):** Operator-hosted on AWS. Tenants are
  isolated logically by `tenant_id`. Shared infrastructure.
- **Mode B — Dedicated single-tenant:** One tenant per deployment, in one of two
  sub-variants:
  - **B1 — Dedicated VPC in operator account:** Isolated VPC, dedicated data stores,
    customer-scoped KMS keys. (Primary single-tenant target.)
  - **B2 — Customer-managed (in the bank's AWS account):** Deployed via IaC into the
    customer's account; data never leaves their boundary. (Documented variant,
    enabled per deal.)

Cloud target is **AWS**. EU customers MUST be deployable in an EU region with data
residency guarantees.

## Glossary

- **Deployment_Mode:** One of `pooled`, `dedicated_vpc`, `customer_managed`.
- **Secrets_Provider:** Abstraction over secret retrieval (env-injected, AWS Secrets
  Manager, or AWS SSM Parameter Store).
- **Identity_Provider (IdP):** External federated identity source (OIDC/SAML) for
  human users; distinct from API-key auth for machine clients.
- **KMS_Provider:** Abstraction over envelope encryption keys (AWS KMS).
- **Object_Store:** Abstraction over blob storage (S3, or S3-compatible MinIO in dev).
- **RBAC:** Role-based access control layered on top of tenant isolation.
- **Tamper_Evident_Log:** An append-only audit log whose entries are hash-chained so
  any modification or deletion is detectable.
- **Data_Residency_Region:** The AWS region to which a tenant's data is pinned.
- **DPA:** Data Processing Agreement (GDPR Art. 28).

## Requirements

### Requirement 1: Deployment-Mode Configuration

**User Story:** As a platform operator, I want one codebase to run in pooled SaaS,
dedicated-VPC, or customer-managed modes, so that I can serve both small fintechs and
banks without forking.

#### Acceptance Criteria

1. THE system SHALL read a `DEPLOYMENT_MODE` setting with allowed values `pooled`,
   `dedicated_vpc`, and `customer_managed`, defaulting to `pooled`.
2. WHERE `DEPLOYMENT_MODE` is `dedicated_vpc` or `customer_managed`, THE system SHALL
   operate as single-tenant and SHALL reject any request whose resolved `tenant_id`
   does not equal the configured `DEDICATED_TENANT_ID` with the uniform
   `resource_not_found` response.
3. THE system SHALL select implementations of Secrets_Provider, KMS_Provider,
   Object_Store, and Identity_Provider at startup from configuration, and application
   code SHALL depend only on their interfaces, never on a concrete provider.
4. THE same container image SHALL run in all three modes with no code changes; mode
   differences SHALL be expressed only through environment/configuration and IaC.
5. WHEN the system starts, THE system SHALL validate that all required configuration
   for the selected Deployment_Mode is present and SHALL fail fast with a descriptive
   error naming each missing key if not.

### Requirement 2: Secrets Management

**User Story:** As a bank security reviewer, I want no plaintext secrets in code,
images, or config files, so that a leaked artifact never exposes credentials.

#### Acceptance Criteria

1. THE system SHALL retrieve all secrets (database credentials, LLM API keys, object
   store keys, signing keys) exclusively through the Secrets_Provider interface.
2. THE system SHALL NOT contain any secret value in source code, the container image,
   logs, or any file committed to version control.
3. WHERE `DEPLOYMENT_MODE` is `pooled` or `dedicated_vpc`, THE Secrets_Provider SHALL
   default to AWS Secrets Manager.
4. THE system SHALL support secret rotation such that a rotated secret takes effect
   without a code deploy, within a bounded refresh interval not exceeding 15 minutes.
5. IF a required secret cannot be retrieved at startup, THEN THE system SHALL fail
   fast and SHALL NOT start serving requests.
6. THE system SHALL redact secret values from all log output, including on exception
   tracebacks.

### Requirement 3: Encryption (At Rest and In Transit)

**User Story:** As a bank, I want all data encrypted at rest and in transit with keys
I can control, so that data exposure is mitigated even if storage is compromised.

#### Acceptance Criteria

1. THE system SHALL serve all external traffic over TLS 1.2 or higher and SHALL
   reject plaintext HTTP for API endpoints.
2. THE system SHALL ensure data at rest in the database, object store, and search
   index is encrypted using KMS-managed keys via the KMS_Provider.
3. WHERE `DEPLOYMENT_MODE` is `dedicated_vpc` or `customer_managed`, THE system SHALL
   support a customer-managed KMS key (CMK) per deployment.
4. THE system SHALL encrypt sensitive document content at the application layer
   (envelope encryption) before persistence, so that storage-level access alone does
   not reveal content.
5. THE system SHALL transmit data between internal services over TLS where services
   cross a trust boundary.

### Requirement 4: Human Identity — SSO (OIDC/SAML) and RBAC

**User Story:** As an enterprise admin, I want my users to sign in via our corporate
IdP with role-based permissions, so that access follows our existing identity
governance.

#### Acceptance Criteria

1. THE system SHALL authenticate human users via an Identity_Provider supporting
   OIDC; SAML 2.0 SHALL be supported for enterprise tenants.
2. THE system SHALL map IdP group/role claims to internal roles drawn from at least:
   `org_admin`, `analyst`, `auditor`, `read_only`.
3. THE system SHALL enforce RBAC such that each role grants a documented set of
   permissions, and an action not permitted for a user's role SHALL be denied.
4. THE `auditor` role SHALL have read access to the audit log and SHALL NOT have
   permission to mutate data or configuration.
5. WHERE a tenant has SSO configured, THE system SHALL be able to enforce that human
   users authenticate only via that tenant's IdP (no password fallback).
6. Machine-to-machine access SHALL continue to use tenant-scoped API keys (existing
   Auth_Service), independent of human SSO.
7. IF an SSO assertion is invalid, expired, or from an untrusted issuer, THEN THE
   system SHALL deny access and SHALL emit an `auth_failure` audit event without
   logging the assertion's secret material.

### Requirement 5: Tamper-Evident, Exportable Audit Log

**User Story:** As a compliance officer, I want an immutable, exportable record of
every privileged action, so that I can satisfy internal audit and regulator inquiries.

#### Acceptance Criteria

1. THE Audit_Log SHALL record every privileged action (authentication outcome, data
   access, configuration change, deletion, export) with actor, action, resource,
   tenant_id, UTC timestamp, and request_id.
2. THE Audit_Log SHALL hash-chain entries such that each entry includes a hash over
   its own content and the previous entry's hash, making any insertion, modification,
   or deletion detectable.
3. THE system SHALL provide a verification operation that confirms the integrity of
   the hash chain for a tenant over a time range and SHALL report the first broken
   link if integrity fails.
4. THE Audit_Log SHALL be exportable per tenant in a machine-readable format suitable
   for ingestion into a customer SIEM, scoped to the requesting tenant only.
5. THE Audit_Log SHALL NOT contain secret values, bearer tokens, or raw PII in any
   entry's detail.
6. THE system SHALL retain audit entries for a configurable retention period (default
   ≥ 365 days) independent of business-data retention.

### Requirement 6: PII Detection and Redaction

**User Story:** As a data protection officer, I want PII detected and redacted from
logs and audit detail, so that we never persist personal data where it doesn't belong.

#### Acceptance Criteria

1. THE PII_Redactor SHALL detect, at minimum, email addresses, phone numbers, credit
   card numbers, IBANs, and national identifiers in text destined for logs or audit
   detail.
2. THE system SHALL redact detected PII before writing to logs or audit entries,
   replacing it with a stable, non-reversible placeholder.
3. THE PII_Redactor SHALL NOT alter the content stored as primary business data
   (documents the customer intentionally indexed); redaction applies to logs,
   telemetry, and audit detail.
4. THE system SHALL provide a configuration to enable strict mode, in which query
   strings are PII-redacted before any logging.
5. THE redaction implementation SHALL be covered by tests demonstrating each supported
   PII class is redacted.

### Requirement 7: Data Residency, Retention, and Erasure

**User Story:** As an EU customer, I want my data pinned to an EU region and erasable
on request, so that we meet GDPR obligations.

#### Acceptance Criteria

1. THE system SHALL pin a tenant's data (database, object store, index) to a
   configured Data_Residency_Region and SHALL NOT replicate tenant data outside that
   region without explicit configuration.
2. THE system SHALL support per-tenant configurable retention for business data, after
   which expired data is deleted within 24 hours of expiry.
3. WHEN a tenant requests erasure ("right to be forgotten"), THE system SHALL delete
   all of that tenant's business data and SHALL emit a `tenant_erasure` audit event
   recording scope and completion timestamp, while preserving the (PII-free) audit log
   for its independent retention period.
4. THE system SHALL document, per Deployment_Mode, where each data category resides.
5. WHERE `DEPLOYMENT_MODE` is `customer_managed`, THE system SHALL ensure no tenant
   business data egresses to the operator's infrastructure (including telemetry).

### Requirement 8: Horizontal Scalability and Statelessness

**User Story:** As an operator, I want the API tier to scale horizontally, so that the
system meets bank load and availability expectations.

#### Acceptance Criteria

1. THE API tier SHALL be stateless such that any instance can serve any request; all
   shared state SHALL reside in the database, cache, object store, or search index.
2. THE system SHALL remove all in-process-only stores from request-serving paths (no
   in-memory document store as a source of truth in production).
3. THE system SHALL use bounded connection pooling for the database and SHALL degrade
   gracefully (shed load with 429/503) rather than exhaust resources under overload.
4. THE system SHALL expose liveness and readiness probes; readiness SHALL report
   unhealthy when a required dependency is unavailable.
5. THE system SHALL support running ≥ 2 API instances behind a load balancer with no
   sticky sessions required for correctness.

### Requirement 9: Observability

**User Story:** As an SRE, I want logs, metrics, and traces, so that I can operate the
system to an SLO and investigate incidents.

#### Acceptance Criteria

1. THE system SHALL emit structured (JSON) logs including request_id and tenant_id
   (never secrets/PII) for every request.
2. THE system SHALL expose metrics covering request rate, error rate, and latency
   percentiles (p50/p95/p99) per endpoint.
3. THE system SHALL emit distributed traces spanning the request across internal
   subsystems, propagating a correlation id.
4. THE system SHALL define and document SLOs for availability and key-endpoint latency.
5. THE observability pipeline SHALL be configurable to send telemetry to a
   customer-controlled destination in dedicated/customer-managed modes.

### Requirement 10: Secure SDLC and Supply Chain

**User Story:** As a bank vendor-risk reviewer, I want evidence of secure development
practices, so that I can approve the vendor.

#### Acceptance Criteria

1. THE CI pipeline SHALL run dependency vulnerability scanning and SHALL fail on
   newly introduced high/critical vulnerabilities.
2. THE CI pipeline SHALL run static application security testing (SAST) and secret
   scanning on every change.
3. THE CI pipeline SHALL build the container image and run image vulnerability
   scanning before publish.
4. THE system SHALL produce a Software Bill of Materials (SBOM) for each release.
5. THE pipeline SHALL pin dependencies to specific versions and SHALL record provenance
   of build artifacts.

### Requirement 11: Infrastructure as Code and Reproducible Deployment

**User Story:** As an operator deploying into a bank's AWS account, I want fully
codified, reproducible infrastructure, so that deployments are auditable and repeatable.

#### Acceptance Criteria

1. THE system SHALL provide Infrastructure-as-Code (Terraform) provisioning all AWS
   resources for each Deployment_Mode (network, data stores, KMS, secrets, compute,
   load balancer).
2. THE IaC SHALL parameterize region, KMS key source (operator vs customer-managed),
   and tenant identity, enabling pooled, dedicated_vpc, and customer_managed targets
   from the same modules.
3. THE deployment SHALL be reproducible from a clean account given the IaC and a
   documented runbook.
4. THE IaC SHALL apply least-privilege IAM roles and SHALL NOT grant wildcard
   administrative permissions to runtime components.
5. THE system SHALL document a rollback procedure for a failed deployment.

### Requirement 12: Availability, Backup, and Disaster Recovery

**User Story:** As a bank, I want defined RPO/RTO with tested backups, so that the
service meets our resilience requirements.

#### Acceptance Criteria

1. THE system SHALL perform automated, encrypted backups of the database and document
   store on a configurable schedule.
2. THE system SHALL document a Recovery Point Objective (RPO) and Recovery Time
   Objective (RTO) and SHALL provide a restore procedure.
3. THE system SHALL support multi-AZ deployment of stateful AWS services in
   pooled and dedicated_vpc modes.
4. THE restore procedure SHALL be verifiable in a non-production environment.

### Requirement 13: Enterprise Frontend (Admin Console & Work Surface)

**User Story:** As an enterprise buyer, I want a polished web application with SSO
login, admin controls, an auditor view, and the analyst work surface, so that my
organization can self-serve administration and use the product without engineering.

#### Acceptance Criteria

1. THE frontend SHALL authenticate human users via the tenant's IdP (OIDC/SAML) with
   no password field, and SHALL present a session-aware application shell that reflects
   the signed-in user's roles.
2. THE frontend SHALL render navigation and actions according to RBAC: a user SHALL NOT
   see or be able to invoke actions their role does not permit (`org_admin`, `analyst`,
   `auditor`, `read_only`).
3. THE frontend SHALL provide an **organization admin console** to: invite/remove users,
   assign roles, view the member list, and configure tenant settings (SSO, data
   residency region, retention policy).
4. THE frontend SHALL provide **API key self-service** to create, name, view (prefix
   only, never the full secret after creation), and revoke tenant-scoped API keys.
5. THE frontend SHALL provide a **usage dashboard** showing per-tenant query/document
   counts and quota consumption against the active plan.
6. THE frontend SHALL provide an **auditor view** (visible to `auditor`/`org_admin`)
   that lists audit entries with filtering by actor/action/time and an export action;
   the view SHALL NOT expose secrets or raw PII.
7. THE frontend SHALL provide the **analyst work surface**: document workspace
   (upload/index, list, delete) and the cited-answer view with verifiable span-level
   citations and live streaming.
8. WHERE the deployment is pooled SaaS, THE frontend SHALL provide **billing & plan
   management** (current plan, usage, invoices via the billing provider portal).
9. THE frontend SHALL surface a **data-control settings** area for org_admin to request
   tenant data erasure and configure retention, with explicit confirmation.
10. THE frontend SHALL be accessible (WCAG 2.1 AA target), responsive, and SHALL not
    log or transmit secrets or PII to third-party analytics.
11. THE frontend SHALL display the active Deployment_Mode and Data_Residency_Region to
    the user so they can confirm where their data resides.

### Requirement 14: Compliance, Legal & Organizational Readiness (Non-Code)

**User Story:** As a founder selling to a Tier-1 financial institution, I want the
non-code prerequisites for vendor onboarding tracked explicitly, so that I do not
mistake a strong codebase for being procurement-ready.

> Note: These items are **out-of-band prerequisites** that code alone cannot satisfy.
> They are recorded here so the overall readiness picture is honest and complete. Each
> typically requires third parties (auditors, lawyers, insurers) and time/money.

#### Acceptance Criteria

1. THE organization SHALL obtain an independent third-party penetration test and
   SHALL remediate findings, retaining the report for buyer review.
2. THE organization SHALL pursue SOC 2 Type II and/or ISO 27001; the technical controls
   in Requirements 1–13 SHALL be mapped to the relevant control families as audit
   evidence.
3. THE organization SHALL maintain the contractual layer required by financial buyers:
   a Data Processing Agreement (GDPR Art. 28), Master Service Agreement, Service Level
   Agreement, and cyber-liability insurance.
4. THE organization SHALL maintain documented operational policies: incident response
   plan with breach-notification timelines, change management, access reviews, and a
   business continuity plan, with a named security owner.
5. THE organization SHALL be an incorporated legal entity (not an individual) capable
   of contracting with a financial institution.
6. THE organization SHALL produce a formal threat model and data-flow diagrams as
   review deliverables, kept current with the architecture.
7. THE platform SHALL implement web-layer protections appropriate to a public endpoint:
   security headers (CSP, HSTS, X-Frame-Options), CSRF protection for session-based
   flows, and a WAF/DDoS layer (e.g., AWS WAF/Shield) in front of the ALB.
