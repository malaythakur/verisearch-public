"""Confidence calibration and evidence accounting for the Answer Engine.

A single "confidence: 100" number is misleading: a numeric answer can be
arithmetically certain while the supporting attribution is missing. This
module decomposes confidence into independent components and computes them
programmatically (not from the LLM's self-report):

- retrieval_confidence: how strongly the retrieval set matched the query,
  derived from result relevance scores.
- evidence_confidence: how well the answer is corroborated, derived from the
  number of distinct documents and distinct sections actually cited.
- reasoning_confidence: lowered when the answer hedges or flags missing
  evidence (e.g. "not explicitly stated", "attribution not available"),
  so an answer that honestly reports a gap is not marked fully confident.

The overall score is a weighted blend that is also capped by the weakest
component, so a serious gap (e.g. no corroborating evidence) meaningfully
drags the headline number down rather than being averaged away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.answer_engine.models import CitationEvent, RetrievalResult

# Approximate size of a "section" when bucketing source offsets, in characters.
_SECTION_BUCKET_CHARS = 2000

# Phrases that signal the model is hedging or flagging missing/insufficient
# evidence. Their presence lowers reasoning_confidence — an honest "not
# available" should not carry a 100 confidence.
_HEDGE_PATTERNS = [
    r"not explicitly (?:stated|available|mentioned|provided)",
    r"not (?:stated|available|mentioned|specified|provided|clear)",
    r"no (?:explicit|specific|direct) (?:information|evidence|data|mention)",
    r"cannot (?:determine|be determined|confirm|verify)",
    r"unable to (?:determine|confirm|verify)",
    r"do(?:es)? not (?:explicitly )?(?:state|mention|specify|provide|contain|include)",
    r"do(?:es)? not (?:appear to )?(?:contain|include|mention)",
    r"(?:sources?|text|document|documents?) (?:do|does) not",
    r"insufficient (?:information|evidence|data)",
    r"unclear",
    r"not enough (?:information|evidence|context)",
    r"attribution (?:is )?(?:not|missing|unavailable)",
]
_HEDGE_RE = re.compile("|".join(_HEDGE_PATTERNS), re.IGNORECASE)

# Signals that the answer deliberately abstained because the question is
# ambiguous / metric-dependent / not determinable from the document. This is a
# correct decision-policy outcome, distinct from a low-quality answer, so it is
# surfaced as its own flag and given a calibrated (moderate) confidence.
_AMBIGUITY_PATTERNS = [
    r"multiple_valid_answers",
    r"multiple valid answers",
    r"not determinable",
    r"not_determinable",
    r"no_supported_answer",
    r"no_supported_counterargument",
    r"no supported (?:answer|counterargument|argument)",
    r"metric[- ]dependent",
    r"depends on (?:which|the) (?:metric|definition|interpretation)",
    r"different metrics? (?:produce|lead to|give|yield)",
    r"no single (?:correct |valid )?answer",
]
_AMBIGUITY_RE = re.compile("|".join(_AMBIGUITY_PATTERNS), re.IGNORECASE)

# Phrases admitting the support is weak/insufficient. If the answer says this
# but does NOT actually abstain, it is contradicting itself (producing a
# weakly-supported answer while conceding it is unsupported) — confidence must
# collapse rather than sit at a comfortable middle value.
_INSUFFICIENT_SUPPORT_PATTERNS = [
    r"insufficient (?:support|evidence|information|data)",
    r"no (?:direct |explicit )?(?:management )?(?:commentary|support) (?:is )?(?:provided|available|present|found)",
    r"not (?:fully |well )?supported",
    r"lacks? (?:sufficient |adequate )?support",
    r"weak(?:ly)? support(?:ed)?",
    r"does not (?:fully )?support",
    r"single source only",
    r"only one source",
    r"timeframe mismatch",
    r"scope mismatch",
]
_INSUFFICIENT_SUPPORT_RE = re.compile(
    "|".join(_INSUFFICIENT_SUPPORT_PATTERNS), re.IGNORECASE
)

# Signals that the answer is REJECTING weaker alternatives or affirming that its
# OWN conclusion is well-grounded. When present, "insufficient support" language
# is about the rejected alternatives (healthy discipline), not a concession that
# the produced answer itself is unsupported — so it must NOT trigger the
# self-contradiction collapse.
_REJECTION_OR_GROUNDED_PATTERNS = [
    r"\breject(?:ed|ing|s)?\b",
    r"not as (?:defensible|supported|strong)",
    r"do(?:es)? not have the same level",
    r"less (?:defensible|supported)",
    r"most (?:defensible|evidence-backed|well-supported)",
    r"grounded in (?:hard )?data",
    r"strong(?:ly)? (?:grounded|supported) (?:in|by)",
    r"is supported by (?:quantitative|hard|the) (?:figures?|data)",
]
_REJECTION_OR_GROUNDED_RE = re.compile(
    "|".join(_REJECTION_OR_GROUNDED_PATTERNS), re.IGNORECASE
)

# Low-information "identity / metadata" escapes: statements that are hard to
# invalidate precisely because they carry almost no report-specific synthesis
# ("the company exists", "has a long history", "was founded N years ago"). When
# these dominate an answer, the system optimized for survivability via vagueness
# instead of an information-rich, well-corroborated conclusion. Detected so the
# headline confidence does not reward a trivially-safe non-answer.
_LOW_INFORMATION_PATTERNS = [
    r"\bhas (?:a )?(?:long|rich|\d+[- ]year) history\b",
    r"\bhas existed\b",
    r"\bhas been (?:in (?:business|operation)|around|operating)\b",
    r"\bfounded (?:in |over )?\d",
    r"\b\d{2,}\s*[- ]?year[- ]old\b",
    r"\bfor (?:over |more than )?\d{2,}\s*years\b",
    r"\bis a (?:large|major|global|leading|significant)\b[^.]{0,60}"
    r"(?:company|institution|bank|firm|presence)",
    r"\blarge (?:and (?:significant|major|global) )?financial institution\b",
    r"\b(?:significant|substantial|major|global) presence\b",
    r"\bcontinues to (?:exist|operate)\b",
]
_LOW_INFORMATION_RE = re.compile("|".join(_LOW_INFORMATION_PATTERNS), re.IGNORECASE)

# Meta-reasoning that reveals the INVERTED robustness objective: optimizing for
# survivability-through-vagueness ("least dependent on details", "most broadly
# supported") instead of information value x evidence redundancy. These are
# unambiguous markers regardless of how many digits the answer contains.
_INVERTED_ROBUSTNESS_PATTERNS = [
    r"\bleast dependent on (?:specific )?(?:details|metrics|data|figures|information)\b",
    r"\bmost broadly supported\b",
    r"\bbroad(?:est|ly)? (?:and|but) (?:general|generic)\b",
    r"\bgeneral enough to (?:survive|remain|withstand)\b",
]
_INVERTED_ROBUSTNESS_RE = re.compile(
    "|".join(_INVERTED_ROBUSTNESS_PATTERNS), re.IGNORECASE
)


@dataclass(frozen=True)
class ConfidenceReport:
    """Decomposed, calibrated confidence for an answer.

    All scores are integers in [0, 100].
    """

    overall: int
    retrieval: int
    reasoning: int
    evidence: int
    sources_used: int
    distinct_sections: int
    hedged: bool
    abstained: bool = False
    # True when the answer admits insufficient/weak support yet still produces a
    # substantive answer instead of abstaining (a self-contradiction). Triggers
    # a confidence collapse.
    support_contradiction: bool = False
    # True when the answer is dominated by low-information identity/metadata
    # ("the company exists / has a long history") instead of a corroborated,
    # information-rich conclusion. Signals an inverted-robustness escape.
    low_information: bool = False
    # Retrieval-integrity fields. The LLM does not perform retrieval (retrieval
    # happens once, in the system, before the model is called), so any claim of
    # "independent re-retrieval" is fabricated. These fields report the actual
    # retrieval composition so corroboration/stability can be judged honestly.
    distinct_documents_retrieved: int = 0
    corroboration_possible: bool = False
    independence_warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "retrieval": self.retrieval,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "sources_used": self.sources_used,
            "distinct_sections": self.distinct_sections,
            "hedged": self.hedged,
            "abstained": self.abstained,
            "support_contradiction": self.support_contradiction,
            "low_information": self.low_information,
            "distinct_documents_retrieved": self.distinct_documents_retrieved,
            "corroboration_possible": self.corroboration_possible,
            "independence_warning": self.independence_warning,
        }


def assess_retrieval_integrity(
    retrieval_results: list[RetrievalResult],
) -> tuple[int, bool, str | None]:
    """Assess whether independent corroboration is structurally possible.

    Returns (distinct_documents, corroboration_possible, warning).

    The model cannot retrieve; it only sees the single retrieval set passed to
    it. Cross-source corroboration or a "second independent retrieval" is only
    meaningful if the retrieval set actually contains more than one distinct
    document. When it does not, any claim of independent verification is invalid
    and we surface SECOND_RETRIEVAL_NOT_INDEPENDENT so callers/UI do not present
    the answer as more corroborated than it is.
    """
    distinct_docs = len({r.document_id for r in retrieval_results})
    if distinct_docs <= 1:
        return (
            distinct_docs,
            False,
            "SECOND_RETRIEVAL_NOT_INDEPENDENT: only "
            f"{distinct_docs} distinct document(s) retrieved; cross-source "
            "corroboration and stability checks are not possible.",
        )
    return distinct_docs, True, None


def _retrieval_confidence(retrieval_results: list[RetrievalResult]) -> int:
    """Score retrieval strength from result relevance scores (0-100)."""
    if not retrieval_results:
        return 0
    top = max(r.score for r in retrieval_results)
    # Scores are normalized to [0, 1]; map to a 50-100 band since a returned
    # result already cleared retrieval filters. A weak top score still implies
    # some uncertainty about whether the right passage was found.
    return int(round(50 + min(max(top, 0.0), 1.0) * 50))


def _evidence_stats(citations: list[CitationEvent]) -> tuple[int, int]:
    """Return (distinct documents cited, distinct sections cited)."""
    docs: set[str] = set()
    sections: set[tuple[str, int]] = set()
    for c in citations:
        docs.add(c.document_id)
        bucket = c.source_start // _SECTION_BUCKET_CHARS
        sections.add((c.document_id, bucket))
    return len(docs), len(sections)


def _evidence_confidence(sources_used: int, distinct_sections: int) -> int:
    """Score corroboration from independent evidence counts (0-100).

    One citation is weak corroboration; multiple distinct sections (and
    especially multiple documents) are stronger.
    """
    if distinct_sections == 0:
        return 30
    if distinct_sections == 1:
        return 65
    # Two or more distinct sections: strong. A second distinct document adds more.
    score = 80 + min(distinct_sections - 2, 3) * 4  # up to 92
    if sources_used >= 2:
        score = min(score + 6, 98)
    return min(score, 98)


def _reasoning_confidence(answer_text: str) -> tuple[int, bool]:
    """Score reasoning soundness; lower it when the answer hedges (0-100).

    Returns (score, hedged).
    """
    hedged = bool(_HEDGE_RE.search(answer_text or ""))
    if not answer_text or not answer_text.strip():
        return 0, hedged
    # Default high — the answer was produced and grounded. A hedge indicates a
    # partial/missing-evidence answer, so cap reasoning confidence lower.
    return (70, True) if hedged else (95, False)


def compute_confidence(
    answer_text: str,
    retrieval_results: list[RetrievalResult],
    citations: list[CitationEvent],
) -> ConfidenceReport:
    """Compute a decomposed, calibrated confidence report for an answer."""
    retrieval = _retrieval_confidence(retrieval_results)
    sources_used, distinct_sections = _evidence_stats(citations)
    evidence = _evidence_confidence(sources_used, distinct_sections)
    reasoning, hedged = _reasoning_confidence(answer_text)
    abstained = bool(_AMBIGUITY_RE.search(answer_text or ""))
    admits_insufficient = bool(_INSUFFICIENT_SUPPORT_RE.search(answer_text or ""))
    # Distinguish a genuine self-contradiction (the answer concedes ITS OWN
    # support is insufficient but completes anyway) from healthy discipline (the
    # answer rejects weaker alternatives, or affirms its own conclusion is
    # data-grounded, while noting the alternatives are less supported). The
    # latter must not be penalized.
    rejects_or_grounded = bool(_REJECTION_OR_GROUNDED_RE.search(answer_text or ""))
    # Self-contradiction: the answer concedes the support is insufficient/weak
    # but did NOT abstain — it produced a substantive answer anyway. This is the
    # "prefers weak completion over disciplined abstention" failure.
    support_contradiction = (
        admits_insufficient and not abstained and not rejects_or_grounded
    )
    # Low-information escape: dominated by identity/metadata language with little
    # numeric/report-specific substance, OR exhibiting the inverted-robustness
    # meta-reasoning (optimizing for vagueness/survivability rather than
    # information value). The digit count is a cheap proxy for information
    # content for the identity-phrase case; the inverted-objective phrases fire
    # regardless of digits.
    digit_count = sum(c.isdigit() for c in (answer_text or ""))
    low_information = not abstained and (
        (bool(_LOW_INFORMATION_RE.search(answer_text or "")) and digit_count < 12)
        or bool(_INVERTED_ROBUSTNESS_RE.search(answer_text or ""))
    )

    distinct_docs, corroboration_possible, independence_warning = (
        assess_retrieval_integrity(retrieval_results)
    )
    # If genuine cross-source corroboration is impossible (single document),
    # evidence confidence cannot reflect independent verification. Cap it so the
    # answer is not presented as more corroborated than the retrieval allows.
    if not corroboration_possible:
        evidence = min(evidence, 65)

    # A deliberate abstention on a genuinely ambiguous question is a CORRECT
    # decision-policy outcome, not a failure. Report it with a calibrated
    # moderate confidence reflecting "the question itself is ambiguous", rather
    # than a low score that would imply the system underperformed.
    if abstained:
        overall = min(60 + (evidence - 30) // 5, 70)
        # A *clean* abstention scores in the moderate band. But if the answer
        # also waded through weak/insufficient evidence before abstaining (the
        # "explored weak completion first" pattern), it is a messier outcome
        # than a crisp early abstention — lower it so the headline reflects that
        # the reasoning was not disciplined.
        if admits_insufficient:
            overall = min(overall, 55)
        overall = max(0, min(overall, 100))
        return ConfidenceReport(
            overall=overall,
            retrieval=retrieval,
            reasoning=reasoning,
            evidence=evidence,
            sources_used=sources_used,
            distinct_sections=distinct_sections,
            hedged=hedged,
            abstained=True,
            support_contradiction=False,
            low_information=False,
            distinct_documents_retrieved=distinct_docs,
            corroboration_possible=corroboration_possible,
            independence_warning=independence_warning,
        )

    # Weighted blend, then cap by the weakest component so a serious gap pulls
    # the headline down rather than being averaged away.
    weighted = retrieval * 0.25 + reasoning * 0.40 + evidence * 0.35
    weakest = min(retrieval, reasoning, evidence)
    overall = int(round(min(weighted, weakest + 15)))

    # Confidence collapse: producing an answer while admitting insufficient
    # support is a serious integrity violation — the headline must reflect that
    # the answer should not be trusted, not sit at a comfortable middle value.
    if support_contradiction:
        overall = min(overall, 30)

    # Low-information escape: a trivially-safe identity/metadata "answer" carries
    # little value; do not reward it with a confident headline.
    if low_information:
        overall = min(overall, 40)

    overall = max(0, min(overall, 100))

    return ConfidenceReport(
        overall=overall,
        retrieval=retrieval,
        reasoning=reasoning,
        evidence=evidence,
        sources_used=sources_used,
        distinct_sections=distinct_sections,
        hedged=hedged,
        abstained=False,
        support_contradiction=support_contradiction,
        low_information=low_information,
        distinct_documents_retrieved=distinct_docs,
        corroboration_possible=corroboration_possible,
        independence_warning=independence_warning,
    )
