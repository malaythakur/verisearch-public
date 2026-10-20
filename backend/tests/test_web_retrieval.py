"""Tests for the live web-retrieval service (wires the dormant crawler)."""

from datetime import datetime, timezone

import pytest

from backend.crawler.models import FetchResult, SkipReason, SkipReasonType
from backend.crawler.web_retrieval import WebRetrievalService, WebRetrievalError


class _FakeFetcher:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        return self._result


class _FakeIndexer:
    def __init__(self):
        self.calls = []

    async def index_document(self, text, source_url, *, tenant_id=""):
        self.calls.append((text, source_url, tenant_id))

        class _R:
            document_id = "doc-1"
            version = 1
            is_new = True
        return _R()


def _ok_html(body: bytes = b"<html><body><h1>Hello</h1><p>World</p></body></html>"):
    return FetchResult(
        content=body,
        fetch_timestamp_utc=datetime.now(timezone.utc),
        http_status=200,
        content_type="text/html",
        canonical_url="https://example.com/page",
    )


def test_rejects_non_http_scheme():
    svc = WebRetrievalService(_FakeFetcher(_ok_html()))
    assert not WebRetrievalService.is_fetchable("file:///etc/passwd")
    assert WebRetrievalService.is_fetchable("https://example.com")


@pytest.mark.asyncio
async def test_fetch_and_extract_html():
    svc = WebRetrievalService(_FakeFetcher(_ok_html()))
    out = await svc.fetch_and_extract("https://example.com/page")
    assert out.http_status == 200
    assert "Hello" in out.text and "World" in out.text
    assert out.indexed is False


@pytest.mark.asyncio
async def test_index_when_requested():
    idx = _FakeIndexer()
    svc = WebRetrievalService(_FakeFetcher(_ok_html()), indexer=idx)
    out = await svc.fetch_and_extract("https://example.com/page", index=True, tenant_id="t1")
    assert out.indexed is True
    assert out.document_id == "doc-1"
    assert idx.calls and idx.calls[0][2] == "t1"


@pytest.mark.asyncio
async def test_skip_reason_raises_policy_error():
    skip = SkipReason(reason=SkipReasonType.DISALLOWED_BY_ROBOTS, url="https://x.com/")
    svc = WebRetrievalService(_FakeFetcher(skip))
    with pytest.raises(WebRetrievalError) as ei:
        await svc.fetch_and_extract("https://x.com/")
    assert ei.value.code == "disallowed_by_robots"


@pytest.mark.asyncio
async def test_non_2xx_raises():
    bad = FetchResult(content=b"x", fetch_timestamp_utc=datetime.now(timezone.utc),
                      http_status=500, content_type="text/html",
                      canonical_url="https://example.com/")
    svc = WebRetrievalService(_FakeFetcher(bad))
    with pytest.raises(WebRetrievalError) as ei:
        await svc.fetch_and_extract("https://example.com/")
    assert ei.value.code == "upstream_error"


@pytest.mark.asyncio
async def test_invalid_scheme_raises():
    svc = WebRetrievalService(_FakeFetcher(_ok_html()))
    with pytest.raises(WebRetrievalError) as ei:
        await svc.fetch_and_extract("ftp://example.com/")
    assert ei.value.code == "invalid_url_scheme"
