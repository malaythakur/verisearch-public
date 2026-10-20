"""Query-aware passage selection for answer-engine context building.

Large documents (annual reports, legal filings, regulatory disclosures) are
indexed as a single blob. Feeding the *head* of such a document to the LLM
means relevant content deep in the document (segment tables, specific clauses)
is never seen, producing "not enough information" or scope-drift answers.

This module splits a document into overlapping passages, ranks them against the
query using a lexical (BM25-ish term frequency) score with a numeric/table bonus,
and returns the most relevant passages within a character budget — in document
order so surrounding context is preserved.

No external API is required: scoring is purely lexical, which is robust for the
table/figure lookups common in financial and legal corpora (the embedding
fallback in this stack is hash-based and not semantically meaningful).
"""

from __future__ import annotations

import re
from collections import Counter

# Common English stopwords plus a few question words that carry no retrieval signal.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "this", "that", "these", "those", "which", "who", "whom", "what",
    "when", "where", "why", "how", "do", "does", "did", "has", "have", "had",
    "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    "about", "into", "over", "after", "before", "between", "all", "any", "some",
    "their", "there", "they", "you", "your", "we", "our", "i", "me", "my",
}

# Query intent words that imply numeric comparison / table lookup.
_NUMERIC_INTENT = {
    "grew", "grow", "growth", "fastest", "highest", "lowest", "largest",
    "smallest", "compare", "comparison", "increase", "increased", "decrease",
    "decreased", "ratio", "rate", "percent", "percentage", "revenue", "income",
    "profit", "loss", "margin", "total", "much", "many", "number", "value",
    "amount", "cost", "expense", "year", "yoy",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.\-%]*")

# Matches numeric values (with optional thousands separators, decimals, %).
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")

# Query intent words that imply the user wants the MOST DEFENSIBLE / evidence-
# backed conclusion (highest evidence density, lowest interpretation). For these
# we bias toward figure-dense / hard-evidence passages and away from narrative.
_DEFENSIBILITY_INTENT = {
    "defensible", "evidence", "evidenced", "supported", "substantiated",
    "rigorous", "objective", "factual", "verifiable", "conclusion",
    "conclude", "justified", "warranted",
}

# Markers of narrative / qualitative sections (CEO letter, mission language)
# that are WEAKER evidence for a "most defensible" question. Passages dominated
# by this language are down-weighted under defensibility intent.
_NARRATIVE_MARKERS = (
    "dear fellow shareholders",
    "letter to shareholders",
    "i am proud",
    "we are proud",
    "our mission",
    "our purpose",
    "long history",
    "committed to",
    "commitment to",
    "we believe",
    "i believe",
    "look forward",
    "our communities",
    "make a difference",
    "play a significant role",
    "advancing economic growth",
)


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _query_terms(query: str) -> list[str]:
    terms = [t for t in _tokenize(query) if t not in _STOPWORDS and len(t) >= 2]
    # De-duplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _split_passages(
    text: str, passage_size: int, overlap: int
) -> list[tuple[int, str]]:
    """Split text into overlapping windows. Returns (start_offset, passage)."""
    passages: list[tuple[int, str]] = []
    n = len(text)
    if n == 0:
        return passages
    start = 0
    step = max(1, passage_size - overlap)
    while start < n:
        end = min(start + passage_size, n)
        passages.append((start, text[start:end]))
        if end >= n:
            break
        start += step
    return passages


def select_relevant_passages(
    query: str,
    text: str,
    *,
    max_chars: int,
    passage_size: int = 1800,
    overlap: int = 300,
) -> str:
    """Return the most query-relevant passages of `text` within `max_chars`.

    If the document already fits within the budget, it is returned unchanged.
    Passages are scored by query-term frequency, with a numeric-content bonus
    when the query implies a comparison/lookup over figures. Selected passages
    are returned in document order, joined with an ellipsis marker so the LLM
    can tell when content was skipped.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    terms = _query_terms(query)
    if not terms:
        # No usable query signal — fall back to the head of the document.
        return text[:max_chars]

    term_set = set(terms)
    numeric_query = bool(term_set & _NUMERIC_INTENT)
    defensibility_query = bool(term_set & _DEFENSIBILITY_INTENT)

    passages = _split_passages(text, passage_size, overlap)
    scored: list[tuple[float, int, int, str]] = []
    for idx, (start, passage) in enumerate(passages):
        tokens = _tokenize(passage)
        if not tokens:
            continue
        tf = Counter(tokens)
        score = float(sum(tf.get(term, 0) for term in terms))
        if score <= 0 and not defensibility_query:
            continue
        # Bonus for distinct query terms present (rewards passages covering the
        # whole question rather than repeating one term).
        distinct = sum(1 for term in terms if term in tf)
        score += distinct
        # Numeric/table bonus: comparison questions are answered by figure-dense
        # passages (segment tables, capital ratios, etc.).
        if numeric_query:
            digit_chars = sum(c.isdigit() for c in passage)
            score += min(digit_chars / 80.0, 4.0)
            # Comparison bonus: a genuine comparison table contains MANY distinct
            # numeric values (one per entity/period). A single anecdote ("12%
            # CAGR in auto loans") has only one or two. Reward passages with
            # several distinct figures so quantitative comparison data outranks
            # narrative commentary.
            distinct_numbers = len(set(_NUMBER_RE.findall(passage)))
            if distinct_numbers >= 4:
                score += min((distinct_numbers - 3) * 0.75, 5.0)
        # Defensibility intent: "most defensible conclusion" means highest
        # evidence density and lowest interpretation. Reward figure-dense
        # passages (hard evidence) and penalize narrative/mission language
        # (CEO letter), which is weaker support for such a conclusion.
        if defensibility_query:
            distinct_numbers = len(set(_NUMBER_RE.findall(passage)))
            score += min(distinct_numbers * 0.6, 6.0)
            lower = passage.lower()
            narrative_hits = sum(1 for m in _NARRATIVE_MARKERS if m in lower)
            score -= narrative_hits * 3.0
        scored.append((score, idx, start, passage))

    if not scored:
        return text[:max_chars]

    # Greedily take the highest-scoring passages within the budget.
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected: list[tuple[int, str]] = []
    total = 0
    for _score, _idx, start, passage in scored:
        if total + len(passage) > max_chars:
            continue
        selected.append((start, passage))
        total += len(passage)
        if total >= max_chars:
            break

    if not selected:
        return text[:max_chars]

    # Return in document order, de-overlapping adjacent passages.
    selected.sort(key=lambda x: x[0])
    parts: list[str] = []
    prev_end = -1
    for start, passage in selected:
        if start <= prev_end:
            # Overlapping with previous selection — append only the new tail.
            overlap_len = prev_end - start
            tail = passage[overlap_len:]
            if tail:
                parts[-1] = parts[-1] + tail
            prev_end = max(prev_end, start + len(passage))
            continue
        if prev_end != -1:
            parts.append("\n[...]\n")
        parts.append(passage)
        prev_end = start + len(passage)

    return "".join(parts)
