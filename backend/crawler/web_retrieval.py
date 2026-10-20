"""Web retrieval service — the live-web capability, wired on top of the crawler.

This restores the genuine "Exa-style" feature that had become dormant: fetching
content from the LIVE WEB (respecting robots.txt, per-host throttling, and the
domain opt-out registry via CrawlFetcher), extracting its text, and optionally
ingesting it into the tenant's corpus so /v1/search and /v1/answer can use it.

It is deliberately a thin orchestration layer:
    CrawlFetcher.fetch(url)  ->  extract_text(...)  ->  IndexerService.index_document(...)

so all the compliance/safety logic (robots, throttle, opt-out, audit) lives in
the existing, tested crawler subsystem rather than being reinvented.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.crawler.fetcher import CrawlFetcher
from backend.crawler.models import FetchResult, SkipReason


# Only fetch http(s) — never file://, data:, etc.
_ALLOWED_SCHEMES = ("http://", "https://")


class WebRetrievalError(Exception):
    """Raised when a URL cannot be fetched or is not eligible."""

    def __init__(self, message: str, *, code: str = "web_fetch_failed") -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class WebFetchOutcome:
    """Result of fetching (and optionally indexing) a single live URL."""

    url: str
    canonical_url: str
    http_status: int
    content_type: str
    text: str
    characters: int
    indexed: bool
    document_id: str | None = None
    version: int | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "characters": self.characters,
            "indexed": self.indexed,
            "document_id": self.document_id,
            "version": self.version,
        }


def _filename_for(url: str, content_type: str) -> str:
    """Pick an extractor-friendly filename so the right parser is chosen."""
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "web.pdf"
    if "html" in ct or "xml" in ct:
        return "web.html"
    if "word" in ct or "officedocument" in ct:
        return "web.docx"
    # Default: treat as HTML (most web pages); the HTML extractor strips tags
    # and degrades gracefully to plain text.
    return "web.html"


class WebRetrievalService:
    """Fetch live web URLs through the crawler and optionally index them."""

    def __init__(self, fetcher: CrawlFetcher, indexer=None) -> None:
        self._fetcher = fetcher
        self._indexer = indexer

    @staticmethod
    def is_fetchable(url: str) -> bool:
        return bool(url) and url.strip().lower().startswith(_ALLOWED_SCHEMES)

    async def fetch_and_extract(
        self, url: str, *, index: bool = False, tenant_id: str = ""
    ) -> WebFetchOutcome:
        """Fetch a live URL (compliance-checked) and extract its text.

        If `index` is True, the extracted text is ingested into the tenant's
        corpus through the standard indexer pipeline.

        Raises WebRetrievalError on ineligible scheme, a crawler skip
        (robots/opt-out), a non-2xx status, or empty/unsupported content.
        """
        from backend.indexer.extractors import ExtractionError, extract_text

        url = (url or "").strip()
        if not self.is_fetchable(url):
            raise WebRetrievalError(
                "only http(s) URLs can be fetched", code="invalid_url_scheme"
            )

        result = await self._fetcher.fetch(url)
        if isinstance(result, SkipReason):
            # Robots / opt-out / robots-unavailable — surfaced honestly.
            raise WebRetrievalError(
                f"URL skipped by crawler policy: {result.reason.value}",
                code=result.reason.value,
            )
        assert isinstance(result, FetchResult)

        if not (200 <= result.http_status < 300):
            raise WebRetrievalError(
                f"upstream returned HTTP {result.http_status}",
                code="upstream_error",
            )
        if not result.content:
            raise WebRetrievalError("fetched content was empty", code="empty_content")

        filename = _filename_for(result.canonical_url, result.content_type)
        try:
            text = extract_text(filename, result.content)
        except ExtractionError as e:
            raise WebRetrievalError(e.message, code=e.code) from e

        # HTML extraction returns raw markup (the indexer normally strips tags
        # at index time). Clean it here too so the returned/extracted text is
        # readable even when not indexed.
        if filename.endswith(".html"):
            try:
                from backend.indexer.cleaner import clean_html
                text = clean_html(text)
            except Exception:
                pass

        if not text.strip():
            raise WebRetrievalError("no extractable text", code="empty_text")

        document_id = version = None
        indexed = False
        if index and self._indexer is not None:
            ir = await self._indexer.index_document(
                text, result.canonical_url, tenant_id=tenant_id
            )
            document_id, version, indexed = ir.document_id, ir.version, True

        return WebFetchOutcome(
            url=url,
            canonical_url=result.canonical_url,
            http_status=result.http_status,
            content_type=result.content_type,
            text=text,
            characters=len(text),
            indexed=indexed,
            document_id=document_id,
            version=version,
        )
