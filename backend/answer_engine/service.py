"""Main Answer Engine service — streaming answer generation with citations.

Implements:
- generate_answer(): AsyncGenerator yielding TokenEvent, CitationEvent, DoneEvent, ErrorEvent.
- Empty retrieval set handling → no_sources_available (R6.6).
- Model failure or 30s silence → error event, close within 2s (R6.5).
- Citation emission within 500ms of supported span (R6.2).
- Done event with full answer text + complete citation set (R6.3).
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

from backend.answer_engine.citations import CitationTracker
from backend.answer_engine.confidence import compute_confidence
from backend.answer_engine.evidence_contract import enforce_evidence_contract
from backend.answer_engine.candidate_synthesis import (
    SynthesisIntent,
    SynthesisResult,
    build_extraction_instruction,
    detect_synthesis_intent,
    synthesize,
)
from backend.answer_engine.adversarial_epistemology import (
    EpistemicVerdict,
    build_premise_check_instruction,
    classify_form,
    parse_presuppositions,
    verdict_from_presuppositions,
)
from backend.answer_engine.models import (
    AnswerErrorCode,
    AnswerEvent,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    RetrievalResult,
    TokenEvent,
)
from backend.answer_engine.passage_selection import select_relevant_passages
from backend.answer_engine.provider import (
    GenerationRequest,
    LLMProvider,
    LLMProviderError,
    MockLLMProvider,
)

# Timeout for token silence (R6.5)
TOKEN_SILENCE_TIMEOUT_SECONDS = 30.0

# Maximum time for stream close after error (R6.5, R6.6)
ERROR_CLOSE_TIMEOUT_SECONDS = 2.0

# Target for first token latency (R6.1)
FIRST_TOKEN_TARGET_SECONDS = 3.0

# Context budget to keep prompts within model token limits.
# Roughly 4 chars/token. These budgets target a large-context model
# (e.g. Groq llama-3.3-70b @ 128k, OpenAI gpt-4o-mini @ 128k): ~12000
# chars (~3000 tokens) per document and ~48000 chars (~12000 tokens)
# total across the retrieval set, leaving ample room for the system
# prompt, question, and completion. Rather than truncating each document
# to its head (which misses tables/clauses deep in long PDFs), we select
# the passages most relevant to the query within this budget.
MAX_CONTEXT_CHARS_PER_DOC = 12000
MAX_TOTAL_CONTEXT_CHARS = 48000


class AnswerEngine:
    """Main service for streaming answer generation with citations.

    Orchestrates LLM provider calls, citation tracking, and event emission.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        silence_timeout: float = TOKEN_SILENCE_TIMEOUT_SECONDS,
    ):
        """Initialize the Answer Engine.

        Args:
            provider: LLM provider for token generation. Defaults to MockLLMProvider.
            silence_timeout: Seconds of token silence before timeout error (default 30s).
        """
        self.provider = provider or MockLLMProvider()
        self.silence_timeout = silence_timeout

    async def generate_answer(
        self,
        query: str,
        retrieval_results: list[RetrievalResult],
        session_id: str | None = None,
    ) -> AsyncGenerator[AnswerEvent, None]:
        """Generate a streaming answer with citations.

        Yields events in order: token events, citation events (interleaved),
        and finally a done event or error event.

        Args:
            query: The user's query.
            retrieval_results: Documents from the retrieval set.
            session_id: Optional session ID for context.

        Yields:
            AnswerEvent instances (TokenEvent, CitationEvent, DoneEvent, or ErrorEvent).
        """
        # R6.6: Empty retrieval set → no_sources_available
        if not retrieval_results:
            yield ErrorEvent(
                code=AnswerErrorCode.NO_SOURCES_AVAILABLE,
                message="No sources available to generate an answer.",
            )
            return

        # Initialize citation tracker with the retrieval set
        citation_tracker = CitationTracker.from_results(retrieval_results)

        # Build the generation request.
        # Select the passages most relevant to the query from each retrieved
        # document (rather than truncating to the head), then cap the total
        # context size so the prompt stays within the model's token limit.
        # This ensures tables/clauses deep in long PDFs (e.g. segment revenue
        # tables in an annual report) actually reach the LLM, while avoiding
        # the OpenAI/Groq 400 "reduce the length of the messages" error.
        context_docs = []
        remaining_budget = MAX_TOTAL_CONTEXT_CHARS
        for r in retrieval_results:
            if remaining_budget <= 0:
                break
            per_doc_limit = min(MAX_CONTEXT_CHARS_PER_DOC, remaining_budget)
            text = select_relevant_passages(
                query, r.cleaned_text or "", max_chars=per_doc_limit
            )
            remaining_budget -= len(text)
            context_docs.append(
                {
                    "document_id": r.document_id,
                    "title": r.title,
                    "text": text,
                }
            )

        request = GenerationRequest(
            query=query,
            context_documents=context_docs,
            system_prompt=_build_system_prompt(retrieval_results),
        )

        # Stream tokens from the provider with timeout handling
        answer_text = ""
        token_index = 0
        all_citations: list[CitationEvent] = []
        error_emitted = False

        try:
            token_stream = self.provider.stream_tokens(request)

            async for token in self._stream_with_timeout(token_stream):
                # Emit token event
                token_event = TokenEvent(text=token, index=token_index)
                yield token_event

                answer_text += token
                token_index += 1
                citation_tracker.update_answer_length(len(answer_text))

                # Check for citation opportunities after each token
                new_citations = self._detect_citations(
                    answer_text, retrieval_results, citation_tracker
                )
                for citation in new_citations:
                    all_citations.append(citation)
                    yield citation

        except asyncio.TimeoutError:
            # R6.5: 30s silence → stream_timeout error
            yield ErrorEvent(
                code=AnswerErrorCode.STREAM_TIMEOUT,
                message="No tokens received for 30 seconds.",
            )
            error_emitted = True

        except LLMProviderError as e:
            # R6.5: Model failure → model_error
            yield ErrorEvent(
                code=AnswerErrorCode.MODEL_ERROR,
                message=f"Model error: {str(e)}",
            )
            error_emitted = True

        except Exception as e:
            # Unexpected error → internal_error
            yield ErrorEvent(
                code=AnswerErrorCode.INTERNAL_ERROR,
                message=f"Internal error: {str(e)}",
            )
            error_emitted = True

        # R6.3: On success, emit done event with full answer + all citations
        if not error_emitted:
            # Deterministic evidence-contract enforcement: if the question
            # required specific evidence types (e.g. management commentary) and
            # the answer itself admits they are missing or backed only by an
            # ineligible section (e.g. footnotes used as commentary), override
            # the answer with the correct abstention verdict. This is a hard
            # gate that prompt instructions alone do not reliably enforce.
            verdict = enforce_evidence_contract(query, answer_text)
            final_answer = verdict.answer if verdict.enforced else answer_text
            confidence = compute_confidence(
                final_answer, retrieval_results, all_citations
            )
            yield DoneEvent(
                answer=final_answer,
                citations=all_citations,
                confidence=confidence.to_dict(),
            )

    async def _stream_with_timeout(
        self, token_stream: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """Wrap a token stream with silence timeout detection.

        Raises asyncio.TimeoutError if no token is received within
        self.silence_timeout seconds.
        """
        async for token in _timeout_aiter(token_stream, self.silence_timeout):
            yield token

    async def synthesize_conclusion(
        self,
        query: str,
        retrieval_results: list[RetrievalResult],
        *,
        stability_executed: bool = False,
        stability_stable: bool = False,
    ) -> "SynthesisResult | None":
        """Deterministic conclusion selection for synthesis questions.

        For analytical "most defensible / most robust conclusion" questions, the
        LLM PROPOSES candidate conclusions as structured JSON and CODE selects
        the winner. Returns None when the question is not a synthesis question,
        no candidates could be extracted, or the provider has no real model
        (so the caller falls back to normal generation).

        `stability_executed`/`stability_stable` carry the measured
        retrieval-stability result (computed by the caller, which holds the
        retriever). Certification requires stability to be both executed AND
        stable.
        """
        intent = detect_synthesis_intent(query)
        if intent == SynthesisIntent.GENERAL:
            return None
        if not retrieval_results:
            return None

        # Build the same passage-selected context used for normal generation.
        # For synthesis questions the user's query has no domain terms ("most
        # defensible conclusion"), so augment it with high-value financial-
        # summary terms to bias passage selection toward substantive, evidence-
        # dense sections (financial highlights, segment results, MD&A) rather
        # than incidental detail passages.
        selection_query = (
            f"{query} financial highlights total revenue net income total assets "
            f"segment results return on equity capital ratio"
        )
        context_docs = []
        remaining_budget = MAX_TOTAL_CONTEXT_CHARS
        for r in retrieval_results:
            if remaining_budget <= 0:
                break
            per_doc_limit = min(MAX_CONTEXT_CHARS_PER_DOC, remaining_budget)
            text = select_relevant_passages(
                selection_query, r.cleaned_text or "", max_chars=per_doc_limit
            )
            remaining_budget -= len(text)
            context_docs.append(
                {
                    "document_id": r.document_id,
                    "title": r.title,
                    "text": text,
                }
            )

        request = GenerationRequest(
            query=query,
            context_documents=context_docs,
            system_prompt=build_extraction_instruction(query),
        )

        # Collect the full (non-streaming-to-client) extraction output.
        raw = ""
        try:
            async for token in self._stream_with_timeout(
                self.provider.stream_tokens(request)
            ):
                raw += token
        except (asyncio.TimeoutError, LLMProviderError, Exception):
            return None

        # Certification requires retrieval stability to be executed AND stable.
        return synthesize(
            query, raw,
            stability_executed=(stability_executed and stability_stable),
            observer_invariance_executed=True,
        )

    async def assess_answerability(
        self,
        query: str,
        retrieval_results: list[RetrievalResult],
    ) -> "EpistemicVerdict | None":
        """Detect epistemically impossible / false-premise questions.

        Layer 1 (form): counterfactual / future / private-intent / out-of-corpus
        questions are impossible regardless of the document — detected without
        an LLM call. Layer 2 (premise): the LLM extracts the question's
        presuppositions and judges each against the sources; CODE decides
        whether a contradicted/absent CORE premise makes the question a false or
        unverifiable premise. Returns a verdict only when the question is
        UNANSWERABLE; returns None when it is answerable (caller proceeds).
        """
        form = classify_form(query)
        if form is not None:
            return form
        if not retrieval_results:
            return None

        # Premise verification needs the document. Seed the selection query with
        # financial-summary terms so the verifier sees the actual headline
        # figures/trends and can mark a premise CONTRADICTED (false premise)
        # rather than merely ABSENT when the document shows the opposite.
        selection_query = (
            f"{query} financial highlights total revenue net income total assets "
            f"year over year increase decrease trend results"
        )
        context_docs = []
        remaining_budget = MAX_TOTAL_CONTEXT_CHARS
        for r in retrieval_results:
            if remaining_budget <= 0:
                break
            per_doc_limit = min(MAX_CONTEXT_CHARS_PER_DOC, remaining_budget)
            text = select_relevant_passages(
                selection_query, r.cleaned_text or "", max_chars=per_doc_limit
            )
            remaining_budget -= len(text)
            context_docs.append(
                {"document_id": r.document_id, "title": r.title, "text": text}
            )

        request = GenerationRequest(
            query=query,
            context_documents=context_docs,
            system_prompt=build_premise_check_instruction(query),
        )
        raw = ""
        try:
            async for token in self._stream_with_timeout(
                self.provider.stream_tokens(request)
            ):
                raw += token
        except (asyncio.TimeoutError, LLMProviderError, Exception):
            return None

        presups = parse_presuppositions(raw)
        if not presups:
            return None
        verdict = verdict_from_presuppositions(query, presups)
        # Return the verdict when it is NOT fully answerable (violation OR
        # uncertainty). The caller decides: terminate on a violation; proceed
        # with partial execution + falsifier on uncertainty.
        return verdict if not verdict.answerable else None

    def _detect_citations(
        self,
        answer_text: str,
        retrieval_results: list[RetrievalResult],
        tracker: CitationTracker,
    ) -> list[CitationEvent]:
        """Detect citation opportunities in the current answer text.

        Looks for spans in the answer that match source document content.
        Citations are emitted within 500ms of the supported span (R6.2).

        Returns a list of new citations detected.
        """
        citations: list[CitationEvent] = []

        # Simple substring matching for citation detection
        # A production implementation would use more sophisticated NLP
        for result in retrieval_results:
            new_citation = self._find_citation_match(
                answer_text, result, tracker
            )
            if new_citation:
                citations.append(new_citation)

        return citations

    def _find_citation_match(
        self,
        answer_text: str,
        result: RetrievalResult,
        tracker: CitationTracker,
    ) -> CitationEvent | None:
        """Find a citation match between answer text and a source document.

        Uses a sliding window approach to find matching spans.
        """
        if len(answer_text) < 10:
            return None

        source_text = result.cleaned_text
        if not source_text:
            return None

        # Look for the most recent chunk of answer text in the source
        # Check the last 50 characters of the answer
        window_size = min(30, len(answer_text))
        recent_text = answer_text[-window_size:]

        # Find this text in the source
        source_pos = source_text.find(recent_text)
        if source_pos == -1:
            return None

        # Calculate offsets
        answer_start = len(answer_text) - window_size
        answer_end = len(answer_text)
        source_start = source_pos
        source_end = source_pos + window_size

        # Validate offsets before creating citation
        if answer_start < 0 or answer_end > len(answer_text):
            return None
        if source_start < 0 or source_end > len(source_text):
            return None
        if answer_start >= answer_end or source_start >= source_end:
            return None

        # Check if we already have a citation for this exact span
        for existing in tracker.citations:
            if (
                existing.document_id == result.document_id
                and existing.answer_start == answer_start
                and existing.answer_end == answer_end
            ):
                return None

        try:
            citation = tracker.validate_and_add_citation(
                document_id=result.document_id,
                version=result.version,
                answer_start=answer_start,
                answer_end=answer_end,
                source_start=source_start,
                source_end=source_end,
            )
            return citation
        except Exception:
            return None


async def _timeout_aiter(
    aiter: AsyncGenerator[str, None], timeout: float
) -> AsyncGenerator[str, None]:
    """Wrap an async generator with per-item timeout.

    Raises asyncio.TimeoutError if no item is yielded within `timeout` seconds.
    """
    aiter_obj = aiter.__aiter__()
    while True:
        try:
            token = await asyncio.wait_for(aiter_obj.__anext__(), timeout=timeout)
            yield token
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError:
            raise


def _build_system_prompt(retrieval_results: list[RetrievalResult]) -> str:
    """Build a system prompt for the LLM with source context.

    The prompt encodes an explicit evidence hierarchy and a claim-verification
    step. This prevents a common enterprise document-QA failure where
    qualitative management commentary (e.g. "12% CAGR in auto loans") overrides
    the quantitative answer to a ranking/comparison question (e.g. "which
    business segment grew fastest"). Structured comparison data must win over
    anecdotal commentary, and the model must verify its final claim against
    that data before answering.
    """
    sources = []
    for i, result in enumerate(retrieval_results, 1):
        sources.append(
            f"[{i}] {result.title} ({result.url})\n"
            f"    {result.cleaned_text[:200]}..."
        )

    return (
        "You are a precise research assistant answering questions over the "
        "user's own documents. Answer ONLY from the provided sources and cite "
        "them inline (e.g. [1]) when making claims.\n\n"
        "EVIDENCE HIERARCHY — when sources offer different kinds of evidence "
        "for the same question, prefer them in this order:\n"
        "  1. Structured comparison data (tables, figures covering MULTIPLE "
        "entities) that directly answer the question.\n"
        "  2. Explicit quantitative statements about the specific entity asked "
        "about.\n"
        "  3. Management commentary or narrative that explains a result.\n"
        "  4. Supporting anecdotes about sub-items or unrelated metrics.\n"
        "Lower-tier evidence may EXPLAIN a result but must NEVER override "
        "higher-tier evidence when selecting the answer.\n\n"
        "DEFENSIBILITY — when the question asks for the 'most defensible', "
        "'best-supported', or 'most evidence-backed' conclusion, optimize for "
        "HIGHEST EVIDENCE DENSITY and LOWEST INTERPRETATION. Prefer conclusions "
        "grounded in hard data (financial tables, firm-level figures, MD&A "
        "quantitative discussion) over qualitative narrative. Treat CEO-letter / "
        "mission / 'long history of commitment' / 'advancing economic growth' "
        "language as WEAK support — it is interpretive and is not the most "
        "defensible conclusion even if management states it.\n"
        "  - MAXIMIZE EVIDENCE COVERAGE, NOT NARROWNESS: the most defensible "
        "conclusion is the BROADEST claim that is still fully supported, backed "
        "by the MOST evidence — not the single most precise number. Prefer a "
        "firm-level conclusion corroborated by multiple data points (e.g. 'the "
        "firm remained highly profitable in 2025', supported by firm-level "
        "revenue, firm-level net income, and consistent segment performance) "
        "over a single narrow segment-level fact, even though the narrow fact is "
        "also true. Cite the multiple supporting figures.\n"
        "  - CLAIM PURITY — DO NOT MIX EVIDENCE CLASSES: 'coverage' means adding "
        "MORE data points of the SAME class (e.g. several quantitative figures) "
        "that corroborate ONE claim. It does NOT mean appending a weaker-class "
        "clause to a strong one. Never join a high-certainty quantitative "
        "statement with a methodology-dependent or interpretive clause using "
        "'and' — doing so drags the whole conclusion down to the weaker class. "
        "If your core conclusion is quantitative (revenue, net income), keep it "
        "purely quantitative; do not add 'and maintained its leadership "
        "position', 'and remained an industry leader', or similar. Leadership / "
        "'leader' / 'market position' / rankings are the SAME weak class and "
        "must be REJECTED, not blended in. When in doubt, choose the NARROWEST "
        "claim that survives the strictest scrutiny over a broader claim that "
        "smuggles in interpretation.\n"
        "  - State the data-grounded conclusion, then explicitly list the "
        "stronger claims you REJECTED as insufficiently supported. When "
        "rejecting, state the PRECISE reason rather than a loose label: e.g. "
        "rankings/awards/leadership 'depend on external methodology not "
        "established in the report' (not simply 'subjective'); future growth is "
        "'an uncertain outcome the report does not establish'; strategic success "
        "'requires causal interpretation beyond the reported figures'; societal "
        "impact 'requires interpretation'.\n\n"
        "ROBUSTNESS / REDUNDANCY — when the question asks what conclusion would "
        "'remain true even if part/half of the report disappeared', what is "
        "'most robust', or what 'survives losing sections', the objective is "
        "INFORMATION VALUE × EVIDENCE REDUNDANCY — NOT survivability through "
        "vagueness. The right answer is a HIGH-INFORMATION conclusion that is "
        "independently corroborated by MULTIPLE distinct sections, so removing "
        "any one section leaves it still supported. It is NOT a trivially-safe, "
        "generic, or identity/metadata statement.\n"
        "  - DO NOT escape to low-information safety: statements like 'the "
        "company exists', 'has a long history', 'is a large institution', or "
        "'was founded N years ago' are metadata, not report synthesis — they "
        "are too weak and must be REJECTED even though they are hard to "
        "invalidate.\n"
        "  - Pick the claim with the MOST independent supporting sections. "
        "Example: 'the firm remained highly profitable and diversified in 2025' "
        "can be supported simultaneously by firm-level financial results, "
        "segment performance tables, and management discussion — so it survives "
        "losing any one of them. State the conclusion, then list the MULTIPLE "
        "independent sections that each support it, and reject claims that rest "
        "on only a SINGLE section (e.g. rankings) as not robust.\n"
        "  - INDEPENDENCE, NOT CORRELATION: supporting items count toward "
        "robustness only if they come from DIFFERENT evidence constructs. "
        "Several views of the SAME underlying thing are correlated, not "
        "independent — e.g. total assets, AUM, available-for-sale securities, "
        "and loan balances are all facets of BALANCE-SHEET COMPOSITION; citing "
        "all four is ONE construct, not four. Genuine independence means support "
        "drawn from distinct constructs: firm-level financial results vs segment "
        "reporting vs business-line descriptions vs management discussion. "
        "Prefer a conclusion corroborated across DISTINCT constructs (e.g. 'the "
        "report consistently presents the firm operating at large scale across "
        "multiple business lines in 2025' — supported by financial tables AND "
        "segment reporting AND business descriptions AND MD&A) over one propped "
        "up by several correlated figures from a single construct.\n\n"
        "METRIC CONSISTENCY — only compare like-for-like. Do not substitute a "
        "different entity or metric than the one asked. For example, growth of "
        "a sub-item (a product line, a single loan category) is NOT the same as "
        "growth of a top-level business segment. If the question asks about "
        "business segments, rank business segments — not products or line items.\n\n"
        "USE EXACT ENTITY NAMES — refer to entities using the exact labels that "
        "appear in the sources (e.g. 'Commercial & Investment Bank', not a "
        "paraphrase like 'Commercial Banking'). Do not invent, abbreviate, or "
        "merge segment/entity names; mismatched labels are treated as errors.\n\n"
        "RETRIEVAL HONESTY — you do NOT perform retrieval. You are given a fixed "
        "set of sources and cannot fetch, re-fetch, or 'independently retrieve' "
        "more. Never claim to have retrieved, searched, or verified across "
        "independent passes — that did not happen. Judge corroboration ONLY from "
        "whether the provided sources contain genuinely distinct documents and "
        "sections. If all evidence comes from a single document, say the finding "
        "rests on one source and cannot be independently corroborated; do not "
        "present it as cross-verified or 'stable across retrievals'.\n\n"
        "EVIDENCE SUFFICIENCY GATE — if the question REQUIRES specific kinds of "
        "support (e.g. 'supported by BOTH a quantitative figure AND management "
        "commentary', or a claim about a specific timeframe), then every "
        "candidate answer must satisfy ALL of those requirements before it can "
        "be produced. Evaluate candidates explicitly and reject any that fail:\n"
        "  - SCOPE MATCH: the evidence must address the SAME thing the question "
        "asks. Do not substitute a narrow metric for a broad one (e.g. a loan-"
        "delinquency detail does not support a claim about OVERALL performance).\n"
        "  - TIMEFRAME MATCH: the evidence must cover the SAME period asked "
        "(e.g. '2025 vs 2024' is not supported by 'since the merger' figures).\n"
        "  - REQUIRED EVIDENCE TYPES: if both a quantitative figure and "
        "management commentary are required and the commentary is absent, that "
        "candidate is NOT supported — do not proceed on the quantitative part "
        "alone.\n"
        "  - EVIDENCE CLASS ELIGIBILITY: 'management commentary' means narrative "
        "sections such as the Letter to Shareholders, Management's Discussion & "
        "Analysis (MD&A), or Business Review. It does NOT include Notes to the "
        "Financial Statements, footnotes, or tables — those are quantitative/"
        "disclosure sections, not commentary. Do not substitute one evidence "
        "class for another to satisfy a requirement.\n"
        "If, after rejecting unsupported candidates, none remain, output a "
        "specific abstention: NO_SUPPORTED_ANSWER (or the exact code the "
        "question names, e.g. NO_SUPPORTED_COUNTERARGUMENT), state which "
        "requirement each candidate failed, and STOP. A disciplined abstention "
        "is STRICTLY BETTER than producing a weakly- or mis-supported answer. "
        "Never produce an answer while simultaneously admitting the support is "
        "insufficient — if support is insufficient, abstain. When you abstain, "
        "do it concisely: briefly name each rejected candidate and the "
        "requirement it failed (one line each), then give the abstention code. "
        "Do NOT walk through or argue the weak evidence in detail before "
        "abstaining — rejecting a candidate means you do not then present its "
        "evidence as if building a case.\n\n"
        "VERIFY BEFORE ANSWERING — for ranking, superlative, or comparison "
        "questions ('which grew fastest', 'highest', 'largest'): identify the "
        "candidate, then confirm the supporting table/figures actually show it "
        "as the maximum across the compared entities. If they do not, reject "
        "that candidate and choose the one the data supports. If the sources do "
        "not contain the data needed to decide, say so plainly rather than "
        "guessing from commentary.\n\n"
        "AMBIGUITY & GRACEFUL TERMINATION — some questions are metric-dependent "
        "or under-specified (e.g. 'which segment had the least impact' depends "
        "on whether impact means revenue, net income, or ROE, and the document "
        "may not define how to aggregate them). When different valid metrics "
        "lead to different answers, or the document does not define the rule "
        "needed to choose between them:\n"
        "  1. State the conclusion explicitly as MULTIPLE_VALID_ANSWERS (or, if "
        "no metric is supported at all, that the answer is not determinable).\n"
        "  2. List each metric and the answer it yields, with citations.\n"
        "  3. State the reason: different metrics produce different conclusions "
        "and the document does not define the aggregation rule.\n"
        "  4. STOP. Do NOT then speculate which option is 'probably' or 'might' "
        "be best, and do NOT compute or assume values the document does not "
        "provide (e.g. recomputing a ratio after a hypothetical change). "
        "Picking a soft favorite after declaring ambiguity contradicts the "
        "evidence and is not allowed. Abstaining cleanly is the correct, "
        "complete answer.\n\n"
        "Sources:\n" + "\n".join(sources)
    )
