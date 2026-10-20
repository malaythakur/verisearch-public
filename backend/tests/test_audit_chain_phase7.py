"""Tests for Enterprise Hardening Phase 7: tamper-evident audit hash-chain + export."""

import json

import pytest

from backend.audit_log.hash_chain import (
    GENESIS_HASH,
    HashChainedAuditEmitter,
    compute_entry_hash,
    verify_chain,
)


async def _emit_some(emitter, tenant="bank-1", n=3):
    for i in range(n):
        await emitter.emit(
            action=f"action_{i}",
            tenant_id=tenant,
            actor="user-1",
            resource=f"/v1/resource/{i}",
            request_id="r" * 16,
            detail={"i": i},
        )


# ---------------------------------------------------------------------------
# Hash chaining + verification (Req 5.2, 5.3)
# ---------------------------------------------------------------------------


class TestHashChain:
    @pytest.mark.asyncio
    async def test_valid_chain_verifies(self):
        em = HashChainedAuditEmitter(seed="s3cr3t")
        await _emit_some(em)
        result = em.verify("bank-1")
        assert result.valid is True
        assert result.first_broken_index is None

    @pytest.mark.asyncio
    async def test_first_entry_links_to_genesis(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, n=1)
        chain = em.chain_for("bank-1")
        assert chain[0]["prev_hash"] == GENESIS_HASH

    @pytest.mark.asyncio
    async def test_each_entry_links_to_previous(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, n=3)
        chain = em.chain_for("bank-1")
        assert chain[1]["prev_hash"] == chain[0]["entry_hash"]
        assert chain[2]["prev_hash"] == chain[1]["entry_hash"]

    @pytest.mark.asyncio
    async def test_tampering_content_detected(self):
        em = HashChainedAuditEmitter(seed="s3cr3t")
        await _emit_some(em, n=3)
        chain = em.chain_for("bank-1")
        # Tamper with the middle entry's content (action), leave hashes intact.
        chain[1]["action"] = "TAMPERED"
        result = verify_chain(chain, seed="s3cr3t")
        assert result.valid is False
        assert result.first_broken_index == 1
        assert "tampered" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_deletion_detected(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, n=3)
        chain = em.chain_for("bank-1")
        # Remove the middle entry -> entry[2].prev_hash no longer matches entry[0].
        broken = [chain[0], chain[2]]
        result = verify_chain(broken)
        assert result.valid is False
        assert result.first_broken_index == 1

    @pytest.mark.asyncio
    async def test_reordering_detected(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, n=3)
        chain = em.chain_for("bank-1")
        reordered = [chain[1], chain[0], chain[2]]
        result = verify_chain(reordered)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_wrong_seed_fails_verification(self):
        em = HashChainedAuditEmitter(seed="correct-seed")
        await _emit_some(em, n=2)
        chain = em.chain_for("bank-1")
        # An attacker without the seed cannot validate the chain.
        result = verify_chain(chain, seed="wrong-seed")
        assert result.valid is False
        assert result.first_broken_index == 0

    @pytest.mark.asyncio
    async def test_per_tenant_chains_independent(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, tenant="bank-1", n=2)
        await _emit_some(em, tenant="bank-2", n=2)
        assert em.verify("bank-1").valid
        assert em.verify("bank-2").valid
        # Different tenants have independent genesis-rooted chains.
        assert em.chain_for("bank-1")[0]["prev_hash"] == GENESIS_HASH
        assert em.chain_for("bank-2")[0]["prev_hash"] == GENESIS_HASH

    def test_empty_chain_is_valid(self):
        assert verify_chain([]).valid is True

    def test_compute_entry_hash_deterministic(self):
        entry = {
            "tenant_id": "t", "actor": "a", "action": "x", "resource": "/r",
            "request_id": "r" * 16, "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "detail": {"k": "v"},
        }
        h1 = compute_entry_hash(entry, GENESIS_HASH, seed="s")
        h2 = compute_entry_hash(entry, GENESIS_HASH, seed="s")
        assert h1 == h2
        assert len(h1) == 64


# ---------------------------------------------------------------------------
# Delegation + export (Req 5.4)
# ---------------------------------------------------------------------------


class TestDelegationAndExport:
    @pytest.mark.asyncio
    async def test_delegates_to_inner(self):
        from backend.audit_log.in_memory import InMemoryAuditEmitter

        inner = InMemoryAuditEmitter()
        em = HashChainedAuditEmitter(inner=inner)
        await _emit_some(em, n=2)
        assert len(inner.events) == 2  # delegated to the wrapped emitter

    @pytest.mark.asyncio
    async def test_export_ndjson_roundtrip(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, n=2)
        ndjson = em.export_ndjson("bank-1")
        lines = ndjson.splitlines()
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert all("entry_hash" in p and "prev_hash" in p for p in parsed)
        # Re-verify the exported (parsed) entries.
        assert verify_chain(parsed).valid is True

    @pytest.mark.asyncio
    async def test_export_scoped_to_tenant(self):
        em = HashChainedAuditEmitter()
        await _emit_some(em, tenant="bank-1", n=2)
        await _emit_some(em, tenant="bank-2", n=3)
        assert len(em.export_ndjson("bank-1").splitlines()) == 2
        assert len(em.export_ndjson("bank-2").splitlines()) == 3
