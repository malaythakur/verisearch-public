FROM python:3.13-slim

WORKDIR /app

# Patch OS packages to pick up fixed Debian security updates, then install curl.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.1

# Upgrade build tooling to clear CRITICAL advisories in the base image's
# pip/setuptools/wheel (e.g. setuptools CVE-2024-6345 / CVE-2025-47273).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy dependency manifest (lock is regenerated in-image to avoid staleness).
COPY pyproject.toml ./

# Resolve + install main dependencies from pyproject. No '|| true' — a failed
# dependency install must fail the build rather than ship a broken image.
RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-interaction --only main --no-root

# Copy backend code into /app/backend/
COPY . /app/backend/

# Set working directory to parent so 'backend.api_gateway' resolves
WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "backend.api_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
