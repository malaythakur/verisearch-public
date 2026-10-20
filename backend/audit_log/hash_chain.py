"""Tamper-evident audit hash-chaining (Enterprise Hardening Phase 7, Req 5.2/5.3).

Each audit entry carries ``prev_hash`` (the previous entry's hash in its tenant chain)
and ``entry_hash = SHA256(seed || canonical(entry) || prev_hash)``. Any insertion,
modification, deletion, or reordering of an entry breaks the chain and is detected by
``verify_chain``, which reports the first broken link.

The chain is computed per tenant so tenants cannot interfere with each other's chains.
The optional ``seed`` is a secret (from the SecretsProvider) so an attacker cannot
recompute a valid chain after tampering without it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

# The canonical-content fields, in fixed order, that are bound into the hash.
_CANONICAL_FIELDS = ("tenant_id", "actor", "action", "resource", "request_id", "timestamp_utc", "detail")

# Genesis hash for the first entry in a tenant chain.
GENESIS_HASH = "0" * 64


def _canonical(entry: dict[str, Any]) -> str:
    """Deterministic JSON of the hashed fields (sorted keys, compact separators)."""
    payload = {k: entry.get(k) for k in _CANONICAL_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(entry: dict[str, Any], prev_hash: str, *, seed: str = "") -> str:
    """Compute the SHA-256 chain hash for ``entry`` given the previous hash."""
    h = hashlib.sha256()
    h.update(seed.encode("utf-8"))
    h.update(_canonical(entry).encode("utf-8"))
    h.update(prev_hash.encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class ChainVerificationResult:
    """Outcome of verifying a hash chain."""

    valid: bool
    # Index of the first entry whose hash does not match (None when valid).
    first_broken_index: int | None = None
    reason: str | None = None


def verify_chain(entries: Iterable[dict[str, Any]], *, seed: str = "") -> ChainVerificationResult:
    """Verify a per-tenant ordered sequence of entries.

    Each entry dict must contain the canonical fields plus ``prev_hash`` and
    ``entry_hash``. Returns the first broken link if integrity fails (Req 5.3).
    """
    prev = GENESIS_HASH
    for idx, entry in enumerate(entries):
        expected_prev = entry.get("prev_hash")
        if expected_prev != prev:
            return ChainVerificationResult(
                valid=False, first_broken_index=idx, reason="prev_hash mismatch"
            )
        recomputed = compute_entry_hash(entry, prev, seed=seed)
        if recomputed != entry.get("entry_hash"):
            return ChainVerificationResult(
                valid=False, first_broken_index=idx, reason="entry_hash mismatch (tampered content)"
            )
        prev = recomputed
    return ChainVerificationResult(valid=True)


class HashChainedAuditEmitter:
    """Wraps an AuditEmitter to add a per-tenant tamper-evident hash chain.

    Maintains the last hash per tenant in memory and records full chained entries
    (including ``prev_hash``/``entry_hash``) for verification and export. Delegates the
    actual persistence to the wrapped emitter so existing storage behavior is unchanged.
    """

    def __init__(self, inner=None, *, seed: str = "") -> None:  # noqa: ANN001
        self._inner = inner
        self._seed = seed
        self._last_hash: dict[str, str] = {}
        self._chain: dict[str, list[dict[str, Any]]] = {}

    def _tenant_key(self, tenant_id: str | None) -> str:
        return tenant_id or "_global"

    async def emit(
        self,
        *,
        action: str,
        tenant_id: str | None,
        actor: str,
        resource: str,
        request_id: str,
        detail: dict,
    ) -> None:
        from datetime import datetime, timezone

        key = self._tenant_key(tenant_id)
        prev = self._last_hash.get(key, GENESIS_HASH)
        entry: dict[str, Any] = {
            "tenant_id": tenant_id,
            "actor": actor,
            "action": action,
            "resource": resource,
            "request_id": request_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "detail": detail,
        }
        entry_hash = compute_entry_hash(entry, prev, seed=self._seed)
        entry["prev_hash"] = prev
        entry["entry_hash"] = entry_hash

        self._chain.setdefault(key, []).append(entry)
        self._last_hash[key] = entry_hash

        if self._inner is not None:
            await self._inner.emit(
                action=action,
                tenant_id=tenant_id,
                actor=actor,
                resource=resource,
                request_id=request_id,
                detail=detail,
            )

    def chain_for(self, tenant_id: str | None) -> list[dict[str, Any]]:
        """Return the recorded chained entries for a tenant."""
        return list(self._chain.get(self._tenant_key(tenant_id), []))

    def verify(self, tenant_id: str | None) -> ChainVerificationResult:
        """Verify the in-memory chain for a tenant."""
        return verify_chain(self.chain_for(tenant_id), seed=self._seed)

    def export_ndjson(self, tenant_id: str | None) -> str:
        """Export a tenant's chain as newline-delimited JSON for SIEM ingest (Req 5.4)."""
        lines = [
            json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
            for entry in self.chain_for(tenant_id)
        ]
        return "\n".join(lines)
