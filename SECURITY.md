# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainer (do not open a public
issue). We aim to acknowledge within 3 business days.

## Automated security gates (CI)

Every push and PR runs `.github/workflows/security.yml`:

| Gate | Tool | Policy |
| --- | --- | --- |
| Dependency vulnerabilities | `pip-audit` | Direct deps kept patched; reviewed transitive advisories tracked below |
| Static analysis (SAST) | `bandit` | Fails on medium+ findings (`-ll`) |
| Secret scanning | `gitleaks` | Fails if a secret is detected |
| Container image scan | `grype` (Anchore) | Fails on CRITICAL (fixed); base-image upgraded via apt |
| SBOM | `syft` (Anchore) | SPDX SBOM published as a build artifact |

## Dependency policy

- Direct, security-critical dependencies (`pyjwt`, `cryptography`) are kept on patched
  versions. They were bumped to clear advisories (`pyjwt>=2.13.0`,
  `cryptography>=44.0.1`).
- Dependencies are pinned in `backend/pyproject.toml`.

### Accepted / tracked transitive advisories

These come from transitive dependencies of the web framework and have no safe upgrade
today without a major framework bump (which carries its own risk). They are tracked
and re-evaluated on every dependency change. None are reachable in an exploitable way
in the current deployment (no multipart form parsing of untrusted large uploads, etc.):

- `starlette` (PYSEC-2026-161, CVE-2025-54121, CVE-2025-62727) — pinned transitively by
  `fastapi 0.115.x`. Revisit when upgrading FastAPI.
- `pytest` (CVE-2025-71176) — dev/test-only dependency, not shipped in the runtime image.
- `pip` (PYSEC-2026-196) — build tooling, not a runtime dependency.

### Accepted / tracked image (interpreter) advisories

The runtime image runs the latest stable Python 3.13 patch (`python:3.13-slim`,
currently 3.13.14), which upgraded the interpreter from 3.11 and **cleared
CVE-2025-13462**. The image scan ignores (see `.grype.yaml`) exactly one remaining
interpreter CVE that has no stable fix:

- CPython `CVE-2026-7210` — the only listed fix is Python `3.15.0b2` (a beta); no
  stable Python release resolves it today, so it cannot be remediated by upgrading
  the base image. Remove this ignore once a stable Python ships the fix.

The container image scan (`grype`) fails the build on **CRITICAL** fixed OS/library
vulnerabilities in the image; the Dockerfile runs `apt-get upgrade` to pull fixed
Debian packages. HIGH findings in upstream base-image packages are frequently
unfixable upstream and would make the gate non-actionable, so the authoritative HIGH
gate for our own Python dependencies is `pip-audit`.

> Note: we deliberately use Anchore Grype rather than Trivy for image scanning — the
> `aquasecurity/trivy-action` tags were subject to a supply-chain compromise
> (CVE-2026-33634, March 2026).

## Secrets

- No secrets are committed to the repository (`.env` is gitignored and was never
  tracked). Secret scanning (`gitleaks`) runs in CI.
- Runtime secrets are resolved via the `SecretsProvider` (AWS Secrets Manager in
  production) and never logged (secret-redaction filter on all log output).
