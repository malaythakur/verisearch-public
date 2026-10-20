"""Regression test: in-memory corpus isolation between tenants.

Reproduces the bug where two signed-in users saw each other's documents:
the in-memory indexer did not tag documents with a tenant, so the /documents
listing and the in-memory search path returned every tenant's docs.

These tests exercise the real IndexerService + RetrieverService (in-memory
path, no OpenSearch) and assert that tenant A cannot see tenant B's documents
via search, while a global (empty-tenant) document remains visible to all.
"""

from __future__ import annotations

import pytest

from backend.indexer.service import IndexerService
from backend.retriever.service import RetrieverService
from backend.retriever.models import SearchRequest, SearchMode


@pytest.fixture
def indexer() -> IndexerService:
    return IndexerService()


@pytest.fixture
def retriever(indexer: IndexerService) -> RetrieverService:
    return RetrieverService(indexer=indexer)


async def _index(indexer: IndexerService, *, url: str, text: str, tenant_id: str) -> str:
    result = await indexer.index_document(text, url, tenant_id=tenant_id)
    # Make the version visible to the retriever (provenance gate).
    versions = indexer.get_document(result.document_id)
    for v in versions:
        v.visible = True
    return result.document_id


@pytest.mark.asyncio
async def test_search_isolates_documents_by_tenant(indexer, retriever):
    await _index(indexer, url="https://a.example/doc", text="alpha quarterly revenue report", tenant_id="user:alice")
    await _index(indexer, url="https://b.example/doc", text="alpha quarterly revenue report", tenant_id="user:bob")

    # Alice searches — she must only see her own document.
    resp_a = retriever.search(
        SearchRequest(query="alpha quarterly revenue", mode=SearchMode.HYBRID, num_results=10, tenant_id="user:alice")
    )
    urls_a = {r.url for r in resp_a.results}
    assert "https://a.example/doc" in urls_a
    assert "https://b.example/doc" not in urls_a

    # Bob searches — he must only see his own document.
    resp_b = retriever.search(
        SearchRequest(query="alpha quarterly revenue", mode=SearchMode.HYBRID, num_results=10, tenant_id="user:bob")
    )
    urls_b = {r.url for r in resp_b.results}
    assert "https://b.example/doc" in urls_b
    assert "https://a.example/doc" not in urls_b


@pytest.mark.asyncio
async def test_global_document_visible_to_all_tenants(indexer, retriever):
    # A document with an empty tenant_id is a global/crawl doc.
    await _index(indexer, url="https://global.example/doc", text="public global knowledge base", tenant_id="")

    for tenant in ("user:alice", "user:bob"):
        resp = retriever.search(
            SearchRequest(query="public global knowledge", mode=SearchMode.HYBRID, num_results=10, tenant_id=tenant)
        )
        assert "https://global.example/doc" in {r.url for r in resp.results}
