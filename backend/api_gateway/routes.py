"""API route handlers for /v1/* endpoints.

Wires the subsystem services to HTTP endpoints:
- POST /v1/search
- POST /v1/find_similar
- POST /v1/contents
- POST /v1/answer
- POST /v1/research
- GET  /v1/research/{job_id}
- GET  /v1/research/{job_id}/events
- POST /v1/sessions
- DELETE /v1/sessions/{session_id}
- POST /v1/pipelines
- GET  /v1/pipelines/{pipeline_id}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api_gateway.rbac_dep import requires
from backend.auth.rbac import Permission

from backend.api_gateway.validation import (
    ContentsRequest,
    FindSimilarRequest,
    RequestValidationError,
    ResearchRequest,
    SearchRequest,
    validate_contents_request,
)


# ---------------------------------------------------------------------------
# Pydantic models for Swagger documentation
# ---------------------------------------------------------------------------


class IndexBody(BaseModel):
    """Request body for POST /v1/index."""
    url: str = Field(..., description="Source URL of the document")
    content: str = Field(..., description="Raw HTML or text content to index")


class SearchBody(BaseModel):
    """Request body for POST /v1/search."""
    query: str = Field(..., description="Search query (1-2048 chars)")
    mode: str = Field(default="hybrid", description="Search mode: neural, keyword, or hybrid")
    num_results: int = Field(default=10, description="Max results to return (0-100)")
    filters: str | None = Field(default=None, description="Filter DSL expression")
    pipeline_id: str | None = Field(default=None, description="Pipeline ID to apply")
    min_credibility: float | None = Field(default=None, description="Min credibility threshold [0.0-1.0]")
    max_ai_generated_likelihood: float | None = Field(default=None, description="Max AI-generated threshold [0.0-1.0]")


class FindSimilarBody(BaseModel):
    """Request body for POST /v1/find_similar."""
    url: str = Field(..., description="URL to find similar documents for")
    num_results: int = Field(default=10, description="Max results (0-100)")
    filters: str | None = Field(default=None, description="Filter DSL expression")


class ContentsBody(BaseModel):
    """Request body for POST /v1/contents."""
    document_ids: list[str] = Field(..., description="List of 1-100 document IDs")
    highlights: bool | None = Field(default=None, description="Include highlight spans (requires query)")
    query: str | None = Field(default=None, description="Query for highlight extraction")
    summary: bool | None = Field(default=None, description="Include document summaries")


class AnswerBody(BaseModel):
    """Request body for POST /v1/answer."""
    query: str = Field(..., description="Question to answer")
    stream: bool = Field(default=True, description="Enable streaming (SSE)")
    session_id: str | None = Field(default=None, description="Session ID for context")


class WebFetchBody(BaseModel):
    """Request body for POST /v1/web/fetch and /v1/web/ingest."""
    url: str = Field(..., description="Live http(s) URL to fetch")
    index: bool = Field(default=False, description="Index the fetched text into the tenant corpus")
    include_text: bool = Field(default=True, description="Return the extracted text in the response")


class ResearchBody(BaseModel):
    """Request body for POST /v1/research."""
    research_goal: str = Field(..., description="Research goal (1-4096 chars)")
    output_schema: dict[str, Any] | None = Field(default=None, description="JSON Schema for structured output")
    session_id: str | None = Field(default=None, description="Session ID for context")
    max_steps: int | None = Field(default=None, description="Max research steps")
    max_duration_ms: int | None = Field(default=None, description="Max duration in ms")
    max_tool_calls: int | None = Field(default=None, description="Max tool calls")


class SessionBody(BaseModel):
    """Request body for POST /v1/sessions."""
    retention_days: int | None = Field(default=14, description="Days to retain session [1-90]")


class PipelineStepBody(BaseModel):
    """A single pipeline step."""
    name: str = Field(..., description="Step name from registry")
    config: dict[str, Any] | None = Field(default=None, description="Step configuration")
    timeout_ms: int | None = Field(default=2000, description="Step timeout [100-30000]ms")


class PipelineBody(BaseModel):
    """Request body for POST /v1/pipelines."""
    name: str = Field(..., description="Pipeline name")
    steps: list[PipelineStepBody] = Field(..., description="Pipeline steps (1-20)")

router = APIRouter(prefix="/v1")

# ---------------------------------------------------------------------------
# In-memory service singletons (initialized lazily on first request)
# In production these would be injected via dependency injection.
# ---------------------------------------------------------------------------

_services: dict[str, Any] = {}


def _get_services() -> dict[str, Any]:
    """Lazily initialize service singletons."""
    if not _services:
        import os

        from backend.indexer import IndexerService
        from backend.retriever.service import RetrieverService
        from backend.answer_engine.service import AnswerEngine
        from backend.answer_engine.provider import OpenAIProvider, MockLLMProvider, ProviderConfig
        from backend.research_agent.service import ResearchAgentService
        from backend.session_store.service import SessionService
        from backend.pipeline_engine.service import PipelineService
        from backend.api_gateway.contents import ContentsService

        indexer = IndexerService()
        retriever = RetrieverService(indexer=indexer)

        # Use real OpenAI provider if API key is set, otherwise mock
        if os.environ.get("OPENAI_API_KEY"):
            provider = OpenAIProvider(ProviderConfig(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini")))
        else:
            provider = MockLLMProvider()

        answer_engine = AnswerEngine(provider=provider)
        research_agent = ResearchAgentService(retriever=retriever)
        session_service = SessionService()
        pipeline_service = PipelineService()
        contents_service = ContentsService(document_store=indexer)

        # Web retrieval service (live-web fetch via the compliance-checked
        # crawler: robots.txt, per-host throttle, domain opt-out, audit).
        web_retrieval = None
        try:
            from backend.crawler.fetcher import CrawlFetcher
            from backend.crawler.robots import RobotsCache
            from backend.crawler.throttle import HostThrottle
            from backend.crawler.opt_out import OptOutRegistry
            from backend.crawler.web_retrieval import WebRetrievalService

            class _NullAudit:
                async def emit(self, **kwargs):  # noqa: ANN003
                    return None

            fetcher = CrawlFetcher(
                robots_cache=RobotsCache(),
                throttle=HostThrottle(),
                opt_out_registry=OptOutRegistry(),
                audit_emitter=_NullAudit(),
            )
            web_retrieval = WebRetrievalService(fetcher, indexer=indexer)
        except Exception:
            web_retrieval = None

        # Kafka ingest producer (optional)
        kafka_producer = None
        try:
            from backend.indexer.kafka_ingest import KafkaIngestProducer
            kafka_producer = KafkaIngestProducer()
        except Exception:
            pass

        _services["indexer"] = indexer
        _services["retriever"] = retriever
        _services["answer_engine"] = answer_engine
        _services["research_agent"] = research_agent
        _services["session_service"] = session_service
        _services["pipeline_service"] = pipeline_service
        _services["contents_service"] = contents_service
        _services["web_retrieval"] = web_retrieval
        _services["kafka_producer"] = kafka_producer

        # Load persisted documents from PostgreSQL on startup
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_load_persisted_documents(indexer))
            else:
                loop.run_until_complete(_load_persisted_documents(indexer))
        except Exception:
            pass

    return _services


def _get_tenant_id(request: Request) -> str:
    """Extract tenant_id from request state (set by auth middleware)."""
    return getattr(request.state, "tenant_id", "test-tenant")


async def _load_persisted_documents(indexer) -> None:
    """Load documents from PostgreSQL into the in-memory indexer on startup."""
    import os
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return

    try:
        import asyncpg
        conn = await asyncpg.connect(database_url)
        # tenant_id may not exist in older local schemas — select defensively.
        try:
            rows = await conn.fetch(
                "SELECT document_id, source_url, version, cleaned_text, tenant_id "
                "FROM documents WHERE visible = TRUE"
            )
        except Exception:
            rows = await conn.fetch(
                "SELECT document_id, source_url, version, cleaned_text "
                "FROM documents WHERE visible = TRUE"
            )
        await conn.close()

        for row in rows:
            # Inject directly into the indexer's in-memory store
            from backend.indexer.service import DocumentVersion
            from backend.indexer.embeddings import generate_embedding
            from datetime import datetime, timezone

            cleaned_text = await _maybe_decrypt_stored(row["cleaned_text"])
            row_tenant = ""
            try:
                row_tenant = str(row["tenant_id"] or "")
            except (KeyError, IndexError):
                row_tenant = ""

            doc_version = DocumentVersion(
                document_id=row["document_id"],
                version=row["version"],
                content_hash="loaded",
                cleaned_text=cleaned_text,
                source_url=row["source_url"],
                last_seen_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                visible=True,
                tenant_id=row_tenant,
            )

            indexer._url_to_doc_id[row["source_url"]] = row["document_id"]
            indexer._documents[row["document_id"]] = [doc_version]

            # Write to in-memory indexes for search
            embedding = generate_embedding(cleaned_text)
            indexer._vector_index.write(row["document_id"], row["version"], embedding)
            indexer._lexical_index.write(row["document_id"], row["version"], cleaned_text)

    except Exception:
        pass


async def _maybe_decrypt_stored(stored: str) -> str:
    """Decrypt a stored cleaned_text value if it is envelope-encrypted.

    Plaintext (non-``enc:v1``) values pass through unchanged, so this is safe for both
    dev (plaintext) and prod (encrypted) storage. Builds the KMS provider from settings.
    """
    try:
        from backend.providers.content_encryption import is_encrypted, ContentEncryptor

        if not is_encrypted(stored):
            return stored
        from backend.config.settings import Settings
        from backend.providers import build_providers

        providers = build_providers(Settings())
        return await ContentEncryptor(providers.kms).decrypt_text(stored)
    except Exception:
        return stored


# ---------------------------------------------------------------------------
# POST /v1/index (convenience endpoint for local dev)
# ---------------------------------------------------------------------------


@router.post("/index", dependencies=[Depends(requires(Permission.INDEX))])
async def index_document(body: IndexBody, request: Request) -> JSONResponse:
    """Index a document (supports async Kafka ingest when available)."""
    if not body.url or not body.content:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "url and content are required"}},
        )

    services = _get_services()
    indexer = services["indexer"]

    # Try Kafka async ingest first
    kafka_producer = services.get("kafka_producer")
    if kafka_producer and kafka_producer.is_available:
        tenant_id = _get_tenant_id(request)
        message_id = await kafka_producer.publish(
            source_url=body.url,
            raw_content=body.content,
            tenant_id=tenant_id,
        )
        return JSONResponse(
            status_code=202,
            content={"message_id": message_id, "status": "queued"},
        )

    # Synchronous indexing
    result = await indexer.index_document(body.content, body.url, tenant_id=_get_tenant_id(request))

    # Persist to PostgreSQL if available
    try:
        await _persist_document(
            result.document_id, body.url, result.version, body.content,
            encryptor=_get_content_encryptor(request),
            tenant_id=_get_tenant_id(request),
        )
    except Exception:
        pass  # DB persistence failure is non-fatal

    return JSONResponse(
        status_code=201,
        content={
            "document_id": result.document_id,
            "version": result.version,
            "is_new": result.is_new,
        },
    )


def _get_content_encryptor(request: Request):
    """Build a ContentEncryptor from app providers when prod KMS is configured.

    Returns None in dev (local KMS) so stored content stays plaintext and debuggable;
    the decrypt path transparently handles both encrypted and plaintext values.
    """
    try:
        settings = request.app.state.settings
        providers = request.app.state.providers
        if getattr(settings, "kms_backend", "local") != "aws":
            return None
        from backend.providers.content_encryption import ContentEncryptor

        return ContentEncryptor(providers.kms)
    except Exception:
        return None


async def _persist_document(
    document_id: str,
    source_url: str,
    version: int,
    content: str,
    *,
    encryptor=None,
    tenant_id: str = "",
) -> None:
    """Persist a document to PostgreSQL for durability.

    When an ``encryptor`` is provided (production KMS), the cleaned text is
    envelope-encrypted at rest (Req 3.4); otherwise it is stored as plaintext.
    """
    import os
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return

    try:
        import asyncpg
        conn = await asyncpg.connect(database_url)
        from backend.indexer.cleaner import clean_html
        from backend.indexer.hasher import compute_content_hash

        cleaned = clean_html(content)
        content_hash = compute_content_hash(cleaned)

        stored_text = cleaned
        if encryptor is not None:
            stored_text = await encryptor.encrypt_text(cleaned, tenant_id=tenant_id)

        await conn.execute("""
            INSERT INTO documents (document_id, source_url, version, content_hash, cleaned_text, tenant_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (source_url) DO UPDATE SET
                version = documents.version + 1,
                content_hash = $4,
                cleaned_text = $5,
                tenant_id = $6,
                updated_at = NOW()
        """, document_id, source_url, version, content_hash, stored_text, tenant_id or None)
        await conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# POST /v1/upload — multipart file upload (PDF/DOCX/TXT/MD/HTML)  (user docs)
# ---------------------------------------------------------------------------


@router.post("/upload", dependencies=[Depends(requires(Permission.INDEX))])
async def upload_document(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a document file, extract its text, and index it.

    Accepts PDF, DOCX, TXT, Markdown, and HTML (<=10MB). The file's text is extracted
    server-side and ingested through the same pipeline as /v1/index. The source URL is
    derived from the filename (upload://<tenant>/<filename>) so re-uploading the same
    file updates the existing document version.
    """
    from backend.indexer.extractors import ExtractionError, extract_text

    filename = file.filename or "upload"
    try:
        data = await file.read()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "upload_read_failed", "message": "could not read upload"}},
        )

    if not data:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "empty_file", "message": "uploaded file is empty"}},
        )

    try:
        text = extract_text(filename, data)
    except ExtractionError as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": e.code, "message": e.message}},
        )

    services = _get_services()
    indexer = services["indexer"]
    tenant_id = _get_tenant_id(request)

    # Stable source URL per (tenant, filename) so re-upload updates the version.
    source_url = f"upload://{tenant_id}/{filename}"
    result = await indexer.index_document(text, source_url, tenant_id=tenant_id)

    try:
        await _persist_document(
            result.document_id, source_url, result.version, text,
            encryptor=_get_content_encryptor(request),
            tenant_id=tenant_id,
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=201,
        content={
            "document_id": result.document_id,
            "version": result.version,
            "is_new": result.is_new,
            "filename": filename,
            "source_url": source_url,
            "characters": len(text),
        },
    )


# ---------------------------------------------------------------------------
# Live web retrieval (the Exa-style capability — fetch from the open web)
# ---------------------------------------------------------------------------


@router.post("/web/fetch", dependencies=[Depends(requires(Permission.SEARCH))])
async def web_fetch(body: WebFetchBody, request: Request) -> JSONResponse:
    """Fetch a LIVE web URL and extract its text.

    Goes through the compliance-checked crawler (robots.txt, per-host throttle,
    domain opt-out). Optionally indexes the result into the tenant corpus
    (set index=true) so /v1/search and /v1/answer can use it. This is the real
    open-web capability, distinct from the local-corpus /v1/search.
    """
    services = _get_services()
    web = services.get("web_retrieval")
    if web is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "web_retrieval_unavailable",
                               "message": "web retrieval is not configured"}},
        )

    from backend.crawler.web_retrieval import WebRetrievalError

    tenant_id = _get_tenant_id(request)
    try:
        outcome = await web.fetch_and_extract(
            body.url, index=bool(body.index), tenant_id=tenant_id
        )
    except WebRetrievalError as e:
        # Policy skips (robots/opt-out) -> 403; bad scheme -> 400; else 502.
        status = 403 if e.code in (
            "disallowed_by_robots", "domain_opted_out", "robots_unavailable"
        ) else (400 if e.code == "invalid_url_scheme" else 502)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": e.code, "message": e.message}},
        )

    # Persist indexed web docs like uploads, so they survive restarts.
    if outcome.indexed and outcome.document_id:
        try:
            await _persist_document(
                outcome.document_id, outcome.canonical_url, outcome.version or 1,
                outcome.text, encryptor=_get_content_encryptor(request), tenant_id=tenant_id,
            )
        except Exception:
            pass

    payload = outcome.to_dict()
    if not body.include_text:
        payload.pop("text", None)
    else:
        payload["text"] = outcome.text
    return JSONResponse(status_code=200, content=payload)


@router.post("/web/ingest", dependencies=[Depends(requires(Permission.INDEX))])
async def web_ingest(body: WebFetchBody, request: Request) -> JSONResponse:
    """Fetch a live web URL and index it into the tenant corpus (convenience).

    Equivalent to /v1/web/fetch with index=true; requires the INDEX permission.
    """
    body.index = True
    return await web_fetch(body, request)


# ---------------------------------------------------------------------------
# Document management: list + delete  (user docs)
# ---------------------------------------------------------------------------


@router.get("/documents", dependencies=[Depends(requires(Permission.INDEX))])
async def list_documents(request: Request) -> JSONResponse:
    """List the indexed documents for the calling tenant (in-memory view)."""
    services = _get_services()
    indexer = services["indexer"]
    tenant_id = _get_tenant_id(request)

    docs = []
    for document_id, versions in indexer.documents.items():
        if not versions:
            continue
        latest = versions[-1]
        # Tenant isolation: only the owning tenant sees its docs. A doc with an
        # empty tenant_id is a global/crawl doc, visible to all.
        doc_tenant = getattr(latest, "tenant_id", "") or ""
        if doc_tenant and doc_tenant != tenant_id:
            continue
        title = (latest.cleaned_text.split("\n")[0][:100] if latest.cleaned_text else "") or latest.source_url
        docs.append(
            {
                "document_id": document_id,
                "source_url": latest.source_url,
                "title": title,
                "version": latest.version,
            }
        )

    return JSONResponse(status_code=200, content={"documents": docs, "total": len(docs)})


@router.delete("/documents/{document_id}", dependencies=[Depends(requires(Permission.INDEX))])
async def delete_document_route(document_id: str, request: Request):
    """Delete a document (all versions) from every store: in-memory, OpenSearch, DB."""
    services = _get_services()
    indexer = services["indexer"]

    existed = indexer.delete_document(document_id)

    # Remove from OpenSearch (best-effort).
    try:
        from backend.retriever.opensearch_client import OpenSearchClient
        OpenSearchClient().delete_document(document_id)
    except Exception:
        pass

    # Remove from PostgreSQL (best-effort).
    try:
        import os
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url:
            import asyncpg
            conn = await asyncpg.connect(database_url)
            try:
                await conn.execute("DELETE FROM documents WHERE document_id = $1", document_id)
            finally:
                await conn.close()
    except Exception:
        pass

    if not existed:
        # Still return 204 if it was only in a persistent store; but if truly absent,
        # report not found for a clean UX.
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "document_not_found", "message": "Document not found"}},
        )

    from fastapi import Response as FastAPIResponse
    return FastAPIResponse(status_code=204)


# ---------------------------------------------------------------------------
# POST /v1/search
# ---------------------------------------------------------------------------


@router.post("/search", dependencies=[Depends(requires(Permission.SEARCH))])
async def search(body: SearchBody, request: Request) -> JSONResponse:
    """Neural, keyword, or hybrid search."""
    # Validate using the strict validator
    try:
        validated = SearchRequest(**body.model_dump())
    except RequestValidationError as e:
        return JSONResponse(status_code=422, content=e.to_response_body())
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(e)}})

    services = _get_services()
    retriever = services["retriever"]
    tenant_id = _get_tenant_id(request)

    from backend.retriever.models import SearchRequest as RetrieverSearchRequest, SearchMode

    search_request = RetrieverSearchRequest(
        query=validated.query,
        mode=SearchMode(validated.mode),
        num_results=validated.num_results,
        filters=validated.filters,
        pipeline_id=validated.pipeline_id,
        min_credibility=validated.min_credibility,
        max_ai_generated_likelihood=validated.max_ai_generated_likelihood,
        tenant_id=tenant_id,
    )

    response = retriever.search(search_request)

    results = [
        {
            "document_id": r.document_id,
            "url": r.url,
            "title": r.title,
            "score": r.score,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "provenance": {
                "credibility_score": r.provenance.credibility_score,
                "ai_generated_likelihood": r.provenance.ai_generated_likelihood,
            },
            "version": r.version,
        }
        for r in response.results
    ]

    return JSONResponse(
        status_code=200,
        content={"results": results, "total": len(results)},
        headers={"X-Index-Version": str(response.index_version)},
    )


# ---------------------------------------------------------------------------
# POST /v1/find_similar
# ---------------------------------------------------------------------------


@router.post("/find_similar", dependencies=[Depends(requires(Permission.SEARCH))])
async def find_similar(body: FindSimilarBody, request: Request) -> JSONResponse:
    """Find documents similar to a URL."""
    try:
        validated = FindSimilarRequest(**body.model_dump())
    except RequestValidationError as e:
        return JSONResponse(status_code=422, content=e.to_response_body())
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(e)}})

    services = _get_services()
    retriever = services["retriever"]
    tenant_id = _get_tenant_id(request)

    from backend.retriever.models import FindSimilarRequest as RetrieverFindSimilarRequest
    from backend.retriever.service import DocumentNotFoundError

    find_request = RetrieverFindSimilarRequest(
        url=validated.url,
        num_results=validated.num_results,
        filters=validated.filters,
        tenant_id=tenant_id,
    )

    try:
        response = retriever.find_similar(find_request)
    except DocumentNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "document_not_found", "message": "URL not found in index"}},
        )

    results = [
        {
            "document_id": r.document_id,
            "url": r.url,
            "title": r.title,
            "score": r.score,
            "provenance": {
                "credibility_score": r.provenance.credibility_score,
                "ai_generated_likelihood": r.provenance.ai_generated_likelihood,
            },
            "version": r.version,
        }
        for r in response.results
    ]

    return JSONResponse(status_code=200, content={"results": results, "total": len(results)})


# ---------------------------------------------------------------------------
# POST /v1/contents
# ---------------------------------------------------------------------------


@router.post("/contents", dependencies=[Depends(requires(Permission.CONTENTS))])
async def contents(body: ContentsBody, request: Request) -> JSONResponse:
    """Batch fetch cleaned text, highlights, summaries."""
    try:
        validated = ContentsRequest(**body.model_dump())
    except RequestValidationError as e:
        return JSONResponse(status_code=422, content=e.to_response_body())
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(e)}})

    # Cross-field validation
    try:
        validate_contents_request(validated)
    except RequestValidationError as e:
        return JSONResponse(status_code=422, content=e.to_response_body())

    services = _get_services()
    contents_service = services["contents_service"]

    response = contents_service.fetch_contents(
        validated.document_ids,
        highlights=validated.highlights,
        query=validated.query,
        summary=validated.summary,
    )

    return JSONResponse(status_code=200, content={"results": contents_service.to_response_dict(response)})


# ---------------------------------------------------------------------------
# POST /v1/answer
# ---------------------------------------------------------------------------


def _measure_retrieval_stability(retriever, query: str, tenant_id: str):
    """Run perturbed independent retrievals and measure agreement.

    Independence perturbations:
      - order:        re-run search (tie/order variation) and read its ranking.
      - chunk:        neural mode (different candidate boundaries than hybrid).
      - decomposition: split the query into sub-queries and union their results.
    Returns a StabilityReport (operational definition of stability).
    """
    from backend.retriever.models import SearchRequest as _SR, SearchMode as _SM
    from backend.answer_engine.retrieval_stability import RetrievalRun, measure_stability

    def _ids(mode, q):
        try:
            resp = retriever.search(_SR(query=q, mode=mode, num_results=8, tenant_id=tenant_id))
            return tuple(r.document_id for r in resp.results)
        except Exception:
            return tuple()

    runs = [
        RetrievalRun("order", _ids(_SM.HYBRID, query), seed=0, chunking_policy="hybrid-default"),
        RetrievalRun("chunk", _ids(_SM.NEURAL, query), seed=1, chunking_policy="neural-knn"),
    ]
    # Decomposition: split on conjunctions / commas into sub-queries, union ids.
    import re as _re
    parts = [p.strip() for p in _re.split(r"\band\b|,|;", query) if len(p.strip()) > 3]
    decomp_ids: list[str] = []
    for p in parts[:3]:
        for did in _ids(_SM.HYBRID, p):
            if did not in decomp_ids:
                decomp_ids.append(did)
    if decomp_ids:
        runs.append(RetrievalRun("decomposition", tuple(decomp_ids), seed=2,
                                 chunking_policy="hybrid-subquery-union"))
    return measure_stability(runs)


@router.post("/answer", dependencies=[Depends(requires(Permission.ANSWER))])
async def answer(body: AnswerBody, request: Request) -> JSONResponse:
    """Streaming answers with citations.

    Returns SSE stream if Accept: text/event-stream, otherwise JSON.
    """
    if not body.query or not body.query.strip():
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_query", "message": "query is required"}},
        )

    # Executability audit (deterministic, document-independent): before spending
    # retrieval/LLM effort, check the REQUEST ITSELF has a single, satisfiable,
    # executable objective. Catches task-incomplete (optimize with no question),
    # contradictory (one word + in detail), and underdetermined (dangling
    # referent) requests.
    from backend.answer_engine.request_executability import assess_executability

    exec_verdict = assess_executability(body.query)
    if not exec_verdict.executable:
        exec_conf = {"overall": 0, "executable": False, "executability": exec_verdict.to_dict()}
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            from backend.api_gateway.sse import SSEEvent, create_sse_response

            async def exec_sse_factory(last_event_id: str | None):
                yield SSEEvent(event="done", data={
                    "answer": exec_verdict.as_answer(), "confidence": exec_conf, "citations": []
                }, id="1")

            return create_sse_response(request, exec_sse_factory)
        return JSONResponse(
            status_code=200,
            content={"answer": exec_verdict.as_answer(), "confidence": exec_conf, "citations": []},
        )

    services = _get_services()
    retriever = services["retriever"]
    answer_engine = services["answer_engine"]
    tenant_id = _get_tenant_id(request)

    # First, retrieve relevant documents
    from backend.retriever.models import SearchRequest as RetrieverSearchRequest, SearchMode
    from backend.answer_engine.models import RetrievalResult, TokenEvent, CitationEvent, DoneEvent, ErrorEvent

    search_request = RetrieverSearchRequest(
        query=body.query,
        mode=SearchMode.HYBRID,
        num_results=5,
        tenant_id=tenant_id,
    )
    search_response = retriever.search(search_request)

    # Convert search results to RetrievalResult format
    retrieval_results = []
    indexer = services["indexer"]
    for r in search_response.results:
        # Prefer in-memory text; fall back to OpenSearch (durable store) so
        # answers still work after a process restart clears the in-memory index.
        cleaned_text = ""
        doc = indexer.get_latest_version(r.document_id)
        if doc:
            cleaned_text = doc.cleaned_text
        else:
            os_text = retriever._opensearch.get_document_text(
                r.document_id, version=r.version, tenant_id=tenant_id
            )
            if os_text:
                cleaned_text = os_text
        if cleaned_text:
            retrieval_results.append(RetrievalResult(
                document_id=r.document_id,
                version=r.version,
                url=r.url,
                title=r.title,
                score=r.score,
                cleaned_text=cleaned_text,
            ))

    # Adversarial-epistemology gate: detect questions that are impossible to
    # answer from the document. Per the graded-execution contract, only a
    # proven VIOLATION (false premise, impossible form) terminates the request;
    # UNCERTAINTY (a premise the document does not establish) does NOT abort —
    # we proceed and attach a partial-execution envelope (falsifier + the
    # unsupported premise) to the answer.
    epistemic_uncertainty = None
    try:
        verdict = await answer_engine.assess_answerability(body.query, retrieval_results)
    except Exception:
        verdict = None
    if verdict is not None and verdict.terminates:
        conf_dict = {
            "overall": 0,
            "answerable": False,
            "epistemic": verdict.to_dict(),
        }
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            from backend.api_gateway.sse import SSEEvent, create_sse_response

            async def epistemic_sse_factory(last_event_id: str | None):
                yield SSEEvent(event="done", data={
                    "answer": verdict.as_answer(), "confidence": conf_dict, "citations": []
                }, id="1")

            return create_sse_response(request, epistemic_sse_factory)
        return JSONResponse(
            status_code=200,
            content={"answer": verdict.as_answer(), "confidence": conf_dict, "citations": []},
        )
    if verdict is not None and not verdict.answerable:
        # Uncertainty (not a violation): keep going, but remember it so the
        # final answer can report what is/ isn't supported and the falsifier.
        epistemic_uncertainty = verdict

    # Measure retrieval stability operationally: run perturbed retrievals
    # (order / chunk-boundary / query-decomposition) and check agreement.
    # Certification depends on this being executed AND stable.
    stability = _measure_retrieval_stability(retriever, body.query, tenant_id)

    # Synthesis questions ("most defensible / most robust conclusion") are
    # selection problems: the LLM proposes candidate conclusions and CODE picks
    # the winner deterministically. If this path produces a result, return it
    # directly (it already contains the conclusion + rejected alternatives).
    try:
        synthesis = await answer_engine.synthesize_conclusion(
            body.query, retrieval_results,
            stability_executed=True, stability_stable=stability.stable,
        )
    except Exception:
        synthesis = None
    if synthesis is not None and synthesis.answer:
        from backend.answer_engine.confidence import compute_confidence as _cc
        from backend.answer_engine.calibration import (
            EvidenceFactors, update_posterior, confidence_label,
        )
        conf = _cc(synthesis.answer, retrieval_results, [])
        conf_dict = conf.to_dict()
        # Operationally-measured retrieval stability.
        conf_dict["retrieval_stability"] = stability.to_dict()
        # Bayesian posterior P(H|E) with monotonic update rules.
        win = synthesis.winner
        w_units = max((s.measures.independent_evidence_units for s in synthesis.pareto_frontier), default=1)
        w_ent = win.min_deletion_size() if win else 1
        posterior = update_posterior(EvidenceFactors(
            independent_units=w_units,
            entailment=w_ent,
            assumption_count=0,
            stability_measured=True,
            stability_stable=stability.stable,
            prerequisites_satisfied=stability.stable,
            hedged=False,
            abstained=(win is None),
        ))
        conf_dict["calibration"] = posterior.to_dict()
        # Qualitative calibration band (DIRECT / STRONG / WEAK / UNSTABLE) —
        # exposed alongside the number so callers can avoid false precision.
        conf_dict["calibration_label"] = confidence_label(
            posterior.posterior, stability.stable, stability.stable
        )
        conf_dict["overall"] = int(round(posterior.posterior * 100))
        conf_dict["synthesis"] = {
            "intent": synthesis.intent.value,
            "winner": synthesis.winner.claim if synthesis.winner else None,
            "partial_conclusion_only": synthesis.winner is None and len(synthesis.pareto_frontier) > 1,
            "frontier_size": len(synthesis.pareto_frontier),
            "rejected_count": len(synthesis.rejected),
            "pareto_frontier": [
                {"claim": s.candidate.claim, "objectives": s.objectives,
                 "measures": s.measures.to_dict()}
                for s in synthesis.pareto_frontier
            ],
            "requirements": list(synthesis.requirements),
        }
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            from backend.api_gateway.sse import SSEEvent, create_sse_response

            async def synth_sse_factory(last_event_id: str | None):
                yield SSEEvent(event="done", data={
                    "answer": synthesis.answer, "confidence": conf_dict, "citations": []
                }, id="1")

            return create_sse_response(request, synth_sse_factory)
        return JSONResponse(
            status_code=200,
            content={"answer": synthesis.answer, "confidence": conf_dict, "citations": []},
        )

    # Check if client wants SSE streaming
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        from backend.api_gateway.sse import SSEEvent, create_sse_response

        async def answer_sse_factory(last_event_id: str | None):
            event_id = 0
            async for event in answer_engine.generate_answer(body.query, retrieval_results, body.session_id):
                event_id += 1
                if isinstance(event, TokenEvent):
                    yield SSEEvent(event="token", data={"text": event.text, "index": event.index}, id=str(event_id))
                elif isinstance(event, CitationEvent):
                    yield SSEEvent(event="citation", data={
                        "document_id": event.document_id, "version": event.version,
                        "answer_start": event.answer_start, "answer_end": event.answer_end,
                        "source_start": event.source_start, "source_end": event.source_end,
                    }, id=str(event_id))
                elif isinstance(event, DoneEvent):
                    yield SSEEvent(event="done", data={"answer": event.answer, "confidence": event.confidence, "citations": [
                        {"document_id": c.document_id, "version": c.version,
                         "answer_start": c.answer_start, "answer_end": c.answer_end}
                        for c in event.citations
                    ]}, id=str(event_id))
                elif isinstance(event, ErrorEvent):
                    yield SSEEvent(event="error", data={"code": event.code.value, "message": event.message}, id=str(event_id))

        return create_sse_response(request, answer_sse_factory)

    # Non-streaming JSON response: collect all events
    full_answer = ""
    citations = []
    confidence = None
    error = None

    async for event in answer_engine.generate_answer(body.query, retrieval_results, body.session_id):
        if isinstance(event, TokenEvent):
            full_answer += event.text
        elif isinstance(event, CitationEvent):
            citations.append({
                "document_id": event.document_id,
                "version": event.version,
                "answer_start": event.answer_start,
                "answer_end": event.answer_end,
                "source_start": event.source_start,
                "source_end": event.source_end,
            })
        elif isinstance(event, DoneEvent):
            full_answer = event.answer
            confidence = event.confidence
            citations = [
                {"document_id": c.document_id, "version": c.version,
                 "answer_start": c.answer_start, "answer_end": c.answer_end}
                for c in event.citations
            ]
        elif isinstance(event, ErrorEvent):
            error = {"code": event.code.value, "message": event.message}

    if error:
        return JSONResponse(status_code=200, content={"error": error})

    # Partial-execution envelope: if a premise was uncertain (not a violation),
    # the answer above is the maximum supported conclusion. Attach what is NOT
    # established and the falsifier so the abstention is operational.
    if epistemic_uncertainty is not None:
        if isinstance(confidence, dict):
            confidence = dict(confidence)
            confidence["executability"] = "partially_executable"
            confidence["epistemic"] = epistemic_uncertainty.to_dict()
        unsupported = [
            p.text for p in epistemic_uncertainty.presuppositions
            if p.status == "ABSENT" and p.is_core
        ]
        envelope = [full_answer, "", "PARTIALLY_EXECUTABLE — supported sub-parts answered above."]
        if unsupported:
            envelope.append("")
            envelope.append("Not established by the document:")
            envelope.extend(f"- {u}" for u in unsupported)
        if epistemic_uncertainty.falsifier:
            envelope.append("")
            envelope.append(f"What would unblock the rest: {epistemic_uncertainty.falsifier}.")
        full_answer = "\n".join(envelope)

    return JSONResponse(
        status_code=200,
        content={"answer": full_answer, "confidence": confidence, "citations": citations},
    )


# ---------------------------------------------------------------------------
# POST /v1/research
# ---------------------------------------------------------------------------


@router.post("/research", dependencies=[Depends(requires(Permission.RESEARCH))])
async def create_research(body: ResearchBody, request: Request) -> JSONResponse:
    """Launch a multi-hop research job."""
    try:
        validated = ResearchRequest(**body.model_dump())
    except RequestValidationError as e:
        return JSONResponse(status_code=422, content=e.to_response_body())
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(e)}})

    services = _get_services()
    research_agent = services["research_agent"]
    tenant_id = _get_tenant_id(request)

    from backend.research_agent.models import BudgetConfig
    from backend.research_agent.service import InvalidResearchRequestError

    budgets = BudgetConfig(
        max_steps=validated.max_steps or 32,
        max_duration_ms=validated.max_duration_ms or 300_000,
        max_tool_calls=validated.max_tool_calls or 100,
    )

    try:
        job_id = research_agent.start_job(
            tenant_id=tenant_id,
            research_goal=validated.research_goal,
            output_schema=validated.output_schema,
            session_id=validated.session_id,
            budgets=budgets,
        )
    except InvalidResearchRequestError as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_research_request", "message": e.message}},
        )

    return JSONResponse(status_code=201, content={"job_id": job_id})


# ---------------------------------------------------------------------------
# GET /v1/research/{job_id}
# ---------------------------------------------------------------------------


@router.get("/research/{job_id}")
async def get_research(job_id: str, request: Request) -> JSONResponse:
    """Get research job report."""
    services = _get_services()
    research_agent = services["research_agent"]
    tenant_id = _get_tenant_id(request)

    from backend.research_agent.service import JobNotFoundError

    try:
        report = research_agent.get_report(job_id, tenant_id)
    except JobNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "job_not_found", "message": "Research job not found"}},
        )

    return JSONResponse(
        status_code=200,
        content={
            "job_id": report.job_id,
            "text": report.text,
            "structured_payload": report.structured_payload,
            "citations": [
                {
                    "citation_id": c.citation_id,
                    "document_id": c.document_id,
                    "version": c.version,
                    "answer_start": c.answer_start,
                    "answer_end": c.answer_end,
                    "source_start": c.source_start,
                    "source_end": c.source_end,
                }
                for c in report.citations
            ],
            "is_partial": report.is_partial,
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/research/{job_id}/events
# ---------------------------------------------------------------------------


@router.get("/research/{job_id}/events")
async def get_research_events(job_id: str, request: Request) -> JSONResponse:
    """Get research job events (simplified JSON response, SSE in production)."""
    services = _get_services()
    research_agent = services["research_agent"]
    tenant_id = _get_tenant_id(request)

    from backend.research_agent.service import JobNotFoundError

    last_event_id = request.headers.get("Last-Event-ID")
    last_id = int(last_event_id) if last_event_id else None

    try:
        events = research_agent.get_events(job_id, tenant_id, last_event_id=last_id)
    except JobNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "job_not_found", "message": "Research job not found"}},
        )

    return JSONResponse(
        status_code=200,
        content={
            "events": [
                {
                    "event_id": e.event_id,
                    "type": e.type.value,
                    "payload": e.payload,
                    "emitted_at": e.emitted_at.isoformat(),
                }
                for e in events
            ],
        },
    )


# ---------------------------------------------------------------------------
# POST /v1/sessions
# ---------------------------------------------------------------------------


@router.post("/sessions", dependencies=[Depends(requires(Permission.SESSION_WRITE))])
async def create_session(body: SessionBody, request: Request) -> JSONResponse:
    """Create a persistent research session."""
    services = _get_services()
    session_service = services["session_service"]
    tenant_id = _get_tenant_id(request)

    from backend.session_store.service import InvalidSessionRequestError

    try:
        session = session_service.create(tenant_id=tenant_id, retention_days=body.retention_days)
    except InvalidSessionRequestError as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_session_request", "message": e.message}},
        )

    return JSONResponse(
        status_code=201,
        content={
            "session_id": session.session_id,
            "tenant_id": session.tenant_id,
            "retention_days": session.retention_days,
            "expires_at": session.expires_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# DELETE /v1/sessions/{session_id}
# ---------------------------------------------------------------------------


@router.delete("/sessions/{session_id}", dependencies=[Depends(requires(Permission.SESSION_WRITE))])
async def delete_session(session_id: str, request: Request):
    """Delete a session."""
    services = _get_services()
    session_service = services["session_service"]
    tenant_id = _get_tenant_id(request)

    from backend.session_store.service import SessionNotFoundError

    try:
        session_service.delete_session(session_id, tenant_id)
    except SessionNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "session_not_found", "message": "Session not found"}},
        )

    # 204 No Content must not carry a response body.
    from fastapi import Response as FastAPIResponse
    return FastAPIResponse(status_code=204)


# ---------------------------------------------------------------------------
# POST /v1/pipelines
# ---------------------------------------------------------------------------


@router.post("/pipelines", dependencies=[Depends(requires(Permission.PIPELINE_WRITE))])
async def create_pipeline(body: PipelineBody, request: Request) -> JSONResponse:
    """Create a retrieval pipeline."""
    if not body.name:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "name is required"}},
        )

    services = _get_services()
    pipeline_service = services["pipeline_service"]
    tenant_id = _get_tenant_id(request)

    from backend.pipeline_engine.service import InvalidPipelineError, UnknownPipelineStepError

    steps = [s.model_dump() for s in body.steps]

    try:
        pipeline = pipeline_service.create_pipeline(tenant_id=tenant_id, name=body.name, steps=steps)
    except InvalidPipelineError as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_pipeline", "message": str(e)}},
        )
    except UnknownPipelineStepError as e:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "unknown_pipeline_step", "message": str(e)}},
        )

    return JSONResponse(
        status_code=201,
        content={
            "pipeline_id": pipeline.pipeline_id,
            "name": pipeline.name,
            "steps": [
                {"name": s.name, "type": s.type.value, "timeout_ms": s.timeout_ms}
                for s in pipeline.steps
            ],
            "created_at": pipeline.created_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/pipelines/{pipeline_id}
# ---------------------------------------------------------------------------


@router.get("/pipelines/{pipeline_id}", dependencies=[Depends(requires(Permission.PIPELINE_READ))])
async def get_pipeline(pipeline_id: str, request: Request) -> JSONResponse:
    """Get a pipeline by ID."""
    services = _get_services()
    pipeline_service = services["pipeline_service"]
    tenant_id = _get_tenant_id(request)

    from backend.pipeline_engine.service import PipelineNotFoundError

    try:
        pipeline = pipeline_service.get_pipeline(pipeline_id, tenant_id)
    except PipelineNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "pipeline_not_found", "message": "Pipeline not found"}},
        )

    return JSONResponse(
        status_code=200,
        content={
            "pipeline_id": pipeline.pipeline_id,
            "name": pipeline.name,
            "steps": [
                {"name": s.name, "type": s.type.value, "config": s.config, "timeout_ms": s.timeout_ms}
                for s in pipeline.steps
            ],
            "created_at": pipeline.created_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/audit/export  (Phase 7, Req 5.4)
# ---------------------------------------------------------------------------


@router.get("/audit/export", dependencies=[Depends(requires(Permission.AUDIT_EXPORT))])
async def export_audit(request: Request):
    """Export the calling tenant's audit log as NDJSON for SIEM ingest.

    Tenant-scoped (a tenant can only export its own entries). Each line includes the
    per-tenant hash-chain fields (prev_hash/entry_hash) computed over the canonical
    entry content, so a downstream consumer can verify integrity. Requires the
    AUDIT_EXPORT permission (auditor/org_admin).
    """
    import os

    from starlette.responses import StreamingResponse

    from backend.audit_log.hash_chain import GENESIS_HASH, compute_entry_hash

    tenant_id = _get_tenant_id(request)
    database_url = os.environ.get("DATABASE_URL", "")

    async def _generate():
        if not database_url:
            return
        try:
            import asyncpg
            import json as _json

            conn = await asyncpg.connect(database_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT tenant_id, actor, action, resource, request_id, timestamp_utc, detail
                    FROM audit_events
                    WHERE tenant_id = $1
                    ORDER BY timestamp_utc ASC, audit_id ASC
                    """,
                    uuid_or_none(tenant_id),
                )
            finally:
                await conn.close()

            prev = GENESIS_HASH
            for row in rows:
                detail = row["detail"]
                if isinstance(detail, str):
                    try:
                        detail = _json.loads(detail)
                    except Exception:
                        detail = {"raw": detail}
                entry = {
                    "tenant_id": str(row["tenant_id"]) if row["tenant_id"] else None,
                    "actor": row["actor"],
                    "action": row["action"],
                    "resource": row["resource"],
                    "request_id": row["request_id"],
                    "timestamp_utc": row["timestamp_utc"].isoformat() if row["timestamp_utc"] else None,
                    "detail": detail,
                }
                entry_hash = compute_entry_hash(entry, prev)
                entry["prev_hash"] = prev
                entry["entry_hash"] = entry_hash
                prev = entry_hash
                yield _json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        except Exception:
            return

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


def uuid_or_none(value: str):
    """Best-effort convert a tenant id string to UUID for the DB query."""
    import uuid as _uuid

    try:
        return _uuid.UUID(value)
    except Exception:
        return value


# ---------------------------------------------------------------------------
# Tenant data lifecycle: residency + erasure (Phase 8, Req 7)
# ---------------------------------------------------------------------------


@router.get("/tenant/residency")
async def tenant_residency(request: Request) -> JSONResponse:
    """Report where the tenant's data resides for the active deployment (Req 7.4)."""
    from backend.api_gateway.data_lifecycle import residency_report
    from backend.config.settings import Settings

    settings = getattr(request.app.state, "settings", None) or Settings()
    return JSONResponse(status_code=200, content=residency_report(settings))


@router.post("/tenant/erasure", dependencies=[Depends(requires(Permission.TENANT_ERASURE))])
async def tenant_erasure(request: Request) -> JSONResponse:
    """Erase the calling tenant's business data; preserve the audit log (Req 7.3).

    Requires the TENANT_ERASURE permission (org_admin). The audit log is retained for
    its independent retention period; a `tenant_erasure` event records the action.
    """
    tenant_id = _get_tenant_id(request)
    request_id = getattr(request.state, "request_id", "") or ("x" * 16)

    from backend.api_gateway.data_lifecycle import TenantErasureService

    object_store = None
    try:
        providers = request.app.state.providers
        object_store = getattr(providers, "object_store", None)
    except Exception:
        object_store = None

    service = TenantErasureService(audit_emitter=None, object_store=object_store)
    result = await service.erase(tenant_id, request_id=request_id)

    return JSONResponse(
        status_code=200,
        content={
            "tenant_id": result.tenant_id,
            "status": result.status,
            "records_deleted": result.records_deleted,
            "audit_preserved": result.audit_preserved,
            "categories": result.categories,
        },
    )


# ---------------------------------------------------------------------------
# GET /v1/me  (Phase 13, Req 13.2) — current principal + permissions
# ---------------------------------------------------------------------------


@router.get("/me")
async def whoami(request: Request) -> JSONResponse:
    """Return the authenticated principal, its roles, and effective permissions.

    Powers the frontend app shell (RBAC-aware nav) and the header's mode/region
    display. Works for both auth planes (SSO human + API-key machine).
    """
    from backend.auth.rbac import permissions_for_roles
    from backend.config.settings import Settings

    principal = getattr(request.state, "principal", None)
    settings = getattr(request.app.state, "settings", None) or Settings()

    if principal is not None:
        roles = list(principal.roles)
        subject = principal.subject
        tenant_id = principal.tenant_id
        auth_kind = principal.auth_kind
    else:
        # Fallback to the tenant resolved by auth middleware (machine plane).
        roles = ["service"]
        subject = getattr(request.state, "api_key_id", "unknown")
        tenant_id = _get_tenant_id(request)
        auth_kind = "machine"

    perms = sorted(p.value for p in permissions_for_roles(tuple(roles)))
    mode = getattr(settings, "deployment_mode", "pooled")

    return JSONResponse(
        status_code=200,
        content={
            "tenant_id": tenant_id,
            "subject": subject,
            "auth_kind": auth_kind,
            "roles": roles,
            "permissions": perms,
            "deployment_mode": getattr(mode, "value", mode),
            "data_residency_region": getattr(settings, "data_residency_region", "unknown"),
        },
    )
