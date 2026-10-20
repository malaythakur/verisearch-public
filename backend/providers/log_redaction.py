"""Secret redaction for logs (Enterprise Hardening Phase 1, Req 2.6).

Provides a registry of known secret values, a ``scrub_secrets()`` helper, and a stdlib
``logging.Filter`` that removes secret values and secret-shaped tokens from every log
record (including handler-rendered exception text). This lives in ``providers`` so it
is importable without depending on the (separate) observability package.
"""

from __future__ import annotations

import logging
import re

# Module-level registry of known secret values to scrub from all log output.
# Seeded at startup by the secret-resolution step. Values are never logged; only their
# presence triggers replacement with a placeholder.
_SECRET_VALUES: set[str] = set()

# Common secret-shaped token patterns scrubbed even if not explicitly registered
# (e.g. a provider key that leaks into a traceback). Conservative to avoid noise.
_SECRET_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:sk|gsk|pk|rk)_[A-Za-z0-9]{16,}\b"),  # OpenAI/Groq-style keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    # AWS access key id
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),       # bearer tokens
)

_SECRET_PLACEHOLDER = "[REDACTED_SECRET]"


def register_secret_values(values: set[str]) -> None:
    """Register known secret values to be scrubbed from logs (Req 2.6)."""
    for v in values:
        if v and len(v) >= 6:  # ignore trivially short values to avoid over-redaction
            _SECRET_VALUES.add(v)


def clear_registered_secrets() -> None:
    """Clear the registry (test helper)."""
    _SECRET_VALUES.clear()


def scrub_secrets(text: str) -> str:
    """Remove registered secret values and secret-shaped tokens from ``text``."""
    if not text:
        return text
    result = text
    for secret in _SECRET_VALUES:
        if secret in result:
            result = result.replace(secret, _SECRET_PLACEHOLDER)
    for pattern in _SECRET_TOKEN_PATTERNS:
        result = pattern.sub(_SECRET_PLACEHOLDER, result)
    return result


class SecretRedactionFilter(logging.Filter):
    """stdlib logging filter that scrubs secret values from records and tracebacks.

    Attach to the root logger so every record — including exception text rendered by
    handlers — is scrubbed before emission (Req 2.6).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = scrub_secrets(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: scrub_secrets(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(
                        scrub_secrets(a) if isinstance(a, str) else a
                        for a in record.args
                    )
            if record.exc_text:
                record.exc_text = scrub_secrets(record.exc_text)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
        return True


def install_secret_redaction_filter() -> SecretRedactionFilter:
    """Attach the redaction filter to the root logger and its handlers."""
    f = SecretRedactionFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for handler in root.handlers:
        handler.addFilter(f)
    return f
