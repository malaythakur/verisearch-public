"""Adversarial epistemology — detecting impossible/unanswerable questions.

Retrieval quality cannot rescue a question that is epistemically impossible to
answer from a static document. A strong system must DETECT and DIAGNOSE these
rather than hallucinate a plausible-sounding answer. Failure modes:

  - FALSE_PREMISE: the question presupposes a fact the document CONTRADICTS
    ("Why did revenue decline in 2025?" when revenue grew). Answering it at all
    validates the false premise.
  - UNVERIFIABLE_PREMISE: the question presupposes something the document cannot
    establish ("How much did the accounting fraud cost?" when no fraud is
    reported). The premise must be challenged, not priced.
  - FUTURE_PREDICTION: asks for an outcome a historical report cannot contain
    ("What will net income be in 2027?").
  - COUNTERFACTUAL: asks about a hypothetical world the report does not describe
    ("What would profit have been if they hadn't operated the investment bank?").
  - PRIVATE_INTENT: asks for unknowable internal mental state ("What does the CEO
    secretly believe about the merger?").
  - OUT_OF_CORPUS: requires data outside the document (a competitor's figures,
    an industry average not reported).

Two detection layers:
  1. FORM-DETECTABLE classes (future, counterfactual, private intent,
     out-of-corpus) are recognized deterministically from the question's shape —
     no document needed, because no document of this type could answer them.
  2. PREMISE-BASED classes (false / unverifiable premise) require checking the
     question's presuppositions AGAINST the document: the LLM extracts the
     presuppositions and judges each as SUPPORTED / CONTRADICTED / ABSENT, and
     CODE decides the verdict. The LLM gathers; code rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# Reuse the tolerant JSON parser used for candidate synthesis.
from backend.answer_engine.candidate_synthesis import _loads_tolerant


class EpistemicCategory(str, Enum):
    ANSWERABLE = "answerable"
    FALSE_PREMISE = "false_premise"
    UNVERIFIABLE_PREMISE = "unverifiable_premise"
    FUTURE_PREDICTION = "future_prediction"
    COUNTERFACTUAL = "counterfactual"
    PRIVATE_INTENT = "private_intent"
    OUT_OF_CORPUS = "out_of_corpus"


class Severity(str, Enum):
    """Whether a problem is a proven VIOLATION or recoverable UNCERTAINTY.

    The distinction is the heart of the graded-execution contract: do NOT
    terminate on uncertainty. A VIOLATION (false premise, impossible form, no
    objective) makes the request non-executable and is the only thing that
    terminates. UNCERTAINTY (evidence may be missing) is PARTIALLY executable —
    report what IS supported plus a falsifier, never a hard abort.
    """

    VIOLATION = "violation"
    UNCERTAINTY = "uncertainty"


class ExecutabilityLevel(str, Enum):
    EXECUTABLE = "executable"
    PARTIALLY_EXECUTABLE = "partially_executable"
    NON_EXECUTABLE = "non_executable"


# Stable codes returned to clients (mirrors the abstention-code style).
_CATEGORY_CODE = {
    EpistemicCategory.FALSE_PREMISE: "FALSE_PREMISE_DETECTED",
    EpistemicCategory.UNVERIFIABLE_PREMISE: "UNVERIFIABLE_PREMISE",
    EpistemicCategory.FUTURE_PREDICTION: "IMPOSSIBLE_FUTURE_PREDICTION",
    EpistemicCategory.COUNTERFACTUAL: "IMPOSSIBLE_COUNTERFACTUAL",
    EpistemicCategory.PRIVATE_INTENT: "IMPOSSIBLE_PRIVATE_INTENT",
    EpistemicCategory.OUT_OF_CORPUS: "OUT_OF_CORPUS",
}

# What evidence/reframing would make each impossible category answerable. A
# falsifier makes the abstention OPERATIONAL: it tells the caller exactly what
# would unblock continuation, rather than just refusing.
_CATEGORY_FALSIFIER = {
    EpistemicCategory.FALSE_PREMISE: (
        "a section of the document that actually supports the assumed fact "
        "(the current evidence shows the opposite)"
    ),
    EpistemicCategory.UNVERIFIABLE_PREMISE: (
        "a section of the document that establishes the assumed fact "
        "(currently the document neither confirms nor denies it)"
    ),
    EpistemicCategory.FUTURE_PREDICTION: (
        "a forward-looking guidance/outlook section with the projected figures "
        "(a historical report does not contain future outcomes)"
    ),
    EpistemicCategory.COUNTERFACTUAL: (
        "a section presenting the hypothetical scenario or a sensitivity/"
        "pro-forma analysis (the report only states what actually occurred)"
    ),
    EpistemicCategory.PRIVATE_INTENT: (
        "a quoted explicit statement of the position in the document "
        "(internal/private mental state is never derivable from a document)"
    ),
    EpistemicCategory.OUT_OF_CORPUS: (
        "the external data (competitor/industry figures) added to the corpus "
        "so the comparison has both sides"
    ),
}


@dataclass(frozen=True)
class Presupposition:
    """A factual claim the question assumes to be true."""

    text: str
    is_core: bool            # the question is meaningless if this is false
    status: str              # SUPPORTED | CONTRADICTED | ABSENT | UNKNOWN


@dataclass(frozen=True)
class EpistemicVerdict:
    """Result of assessing whether a question is answerable from the document."""

    answerable: bool
    category: EpistemicCategory
    code: str | None
    reason: str
    presuppositions: tuple[Presupposition, ...] = ()
    severity: Severity = Severity.VIOLATION
    falsifier: str | None = None

    @property
    def terminates(self) -> bool:
        """Only a VIOLATION terminates the request; UNCERTAINTY does not."""
        return (not self.answerable) and self.severity == Severity.VIOLATION

    def to_dict(self) -> dict:
        return {
            "answerable": self.answerable,
            "category": self.category.value,
            "code": self.code,
            "reason": self.reason,
            "severity": self.severity.value,
            "falsifier": self.falsifier,
            "presuppositions": [
                {"text": p.text, "is_core": p.is_core, "status": p.status}
                for p in self.presuppositions
            ],
        }

    def as_answer(self) -> str:
        """Render the verdict as the user-facing answer for impossible questions."""
        lines = [self.code or "UNANSWERABLE_QUESTION", "", self.reason]
        contradicted = [p for p in self.presuppositions if p.status == "CONTRADICTED"]
        absent = [p for p in self.presuppositions if p.status == "ABSENT"]
        if contradicted:
            lines.append("")
            lines.append("Presuppositions the document CONTRADICTS:")
            for p in contradicted:
                lines.append(f"- {p.text}")
        if absent:
            lines.append("")
            lines.append("Presuppositions the document does NOT establish:")
            for p in absent:
                lines.append(f"- {p.text}")
        if self.falsifier:
            lines.append("")
            lines.append(f"What would unblock this: {self.falsifier}.")
        lines.append("")
        lines.append(
            "Rather than answer a question built on this, the premise itself "
            "must be corrected or the question reframed."
        )
        return "\n".join(lines)


# --- Layer 1: form-detectable impossibility -----------------------------------

# Future prediction: asks for a value/outcome that a historical report cannot
# contain. Requires a predictive frame, not just the word "will" (which appears
# in forward-looking-statement disclaimers).
_FUTURE_RE = re.compile(
    r"\b(?:what|how much|how many)\b[^?]*\b(?:will|going to|expected to|"
    r"projected to|forecast(?:ed)?|predict(?:ed)?)\b[^?]*\b(?:be|become|reach|"
    r"grow|rise|fall|increase|decrease|change)\b|"
    r"\bnext\s+(?:year|quarter|fiscal\s+year|decade)\b|"
    r"\bin\s+20(?:2[6-9]|[3-9]\d)\b|"  # any year after the 2025 report
    r"\b(?:predict|forecast|project)\b[^?]*\b(?:future|upcoming|coming)\b",
    re.IGNORECASE,
)

# Counterfactual: a hypothetical world the report does not describe.
_COUNTERFACTUAL_RE = re.compile(
    r"\bwhat\s+(?:would|might|could)\b[^?]*\bif\b[^?]*"
    r"(?:had(?:n't|\s+not)?|were(?:n't)?|did\s*n['’]?t|hadn['’]?t|instead)\b|"
    r"\bif\b[^?]*\bhad(?:n['’]?t|\s+not)\b|"
    r"\bwould\s+have\s+been\b[^?]*\bif\b",
    re.IGNORECASE,
)

# Private/unknowable mental state.
_PRIVATE_INTENT_RE = re.compile(
    r"\b(?:secretly|privately|really\s+(?:think|believe|feel|want)|"
    r"true\s+(?:motivation|intention|reason|feeling)s?|hidden\s+agenda|"
    r"behind\s+closed\s+doors|personal(?:ly)?\s+(?:think|believe|feel))\b",
    re.IGNORECASE,
)

# Out-of-corpus: explicitly asks to compare with external entities or averages
# the document is not expected to contain. Conservative — only fires on clear
# external-reference language.
_OUT_OF_CORPUS_RE = re.compile(
    r"\b(?:compared?\s+(?:to|with)|versus|vs\.?)\s+(?:its\s+)?"
    r"(?:competitors?|peers?|the\s+industry|other\s+banks?|the\s+market)\b|"
    r"\bindustry\s+average\b|\bmarket\s+share\s+of\s+(?:competitors?|rivals?)\b|"
    r"\bwhat\s+do\s+(?:analysts?|investors?|critics?)\s+(?:say|think)\b",
    re.IGNORECASE,
)


def classify_form(query: str) -> EpistemicVerdict | None:
    """Detect form-impossible questions without needing the document.

    Returns a verdict for an impossible class, or None if the question is not
    form-impossible (it may still have a false premise — see the premise check).
    """
    q = query or ""
    if _COUNTERFACTUAL_RE.search(q):
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.COUNTERFACTUAL,
            code=_CATEGORY_CODE[EpistemicCategory.COUNTERFACTUAL],
            reason=(
                "This is a counterfactual question about a hypothetical scenario "
                "the report does not describe. A factual report can only state "
                "what occurred, not what would have happened under different "
                "conditions; the answer cannot be established from it."
            ),
            severity=Severity.VIOLATION,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.COUNTERFACTUAL],
        )
    if _FUTURE_RE.search(q):
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.FUTURE_PREDICTION,
            code=_CATEGORY_CODE[EpistemicCategory.FUTURE_PREDICTION],
            reason=(
                "This asks for a future outcome. A historical report documents a "
                "period that has already ended and cannot establish future "
                "values; any figure would be speculation, not evidence."
            ),
            severity=Severity.VIOLATION,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.FUTURE_PREDICTION],
        )
    if _PRIVATE_INTENT_RE.search(q):
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.PRIVATE_INTENT,
            code=_CATEGORY_CODE[EpistemicCategory.PRIVATE_INTENT],
            reason=(
                "This asks for an unknowable internal mental state (private "
                "beliefs, true motivations). A document can report stated "
                "positions but cannot establish what someone privately thinks; "
                "the answer is not derivable from it."
            ),
            severity=Severity.VIOLATION,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.PRIVATE_INTENT],
        )
    if _OUT_OF_CORPUS_RE.search(q):
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.OUT_OF_CORPUS,
            code=_CATEGORY_CODE[EpistemicCategory.OUT_OF_CORPUS],
            reason=(
                "This requires data outside the document (external competitors, "
                "industry averages, or third-party opinions). The document is "
                "not expected to contain it, so the comparison cannot be made "
                "from this source alone."
            ),
            severity=Severity.VIOLATION,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.OUT_OF_CORPUS],
        )
    return None


# Meta/triviality presuppositions that every question implicitly makes and that
# must never, on their own, render a question impossible.
_META_PRESUPPOSITION_RE = re.compile(
    r"\b(?:data|figures?|numbers?|information|report|sources?|document)\b[^.]*"
    r"\b(?:is|are)\b[^.]*\b(?:accurate|reliable|correct|complete|valid|"
    r"available|present|consistent|trustworthy)\b|"
    r"\bthe\s+report\s+(?:exists|is\s+complete|is\s+accurate)\b|"
    r"\bsources?\s+(?:are\s+)?(?:reliable|accurate|trustworthy)\b",
    re.IGNORECASE,
)


# --- Layer 2: premise verification (LLM gathers, code rules) ------------------

def build_premise_check_instruction(query: str) -> str:
    """Instruction for the LLM to extract & verify the question's presuppositions.

    The LLM does NOT answer the question. It lists the factual claims the
    question ASSUMES, and judges each against the provided sources.
    """
    return (
        "Do NOT answer the question. Instead, identify the factual "
        "PRESUPPOSITIONS the question assumes to be true, and check each against "
        "the provided sources. Return ONLY a JSON array, no prose. Each element:\n"
        '  "presupposition": the assumed fact, stated plainly,\n'
        '  "is_core": true if the question becomes meaningless when this '
        "presupposition is false,\n"
        '  "status": one of "SUPPORTED" (the sources state it), "CONTRADICTED" '
        "(the sources state the opposite), or \"ABSENT\" (the sources neither "
        "confirm nor deny it).\n"
        "Be strict: if the question asserts a trend/event/condition (e.g. a "
        "decline, a loss, a fraud, a resignation) check whether the sources "
        "actually show it. If the sources show the OPPOSITE, mark CONTRADICTED. "
        "For example, if the question assumes 'revenue declined' but the sources "
        "show revenue INCREASED year over year, the presupposition 'revenue "
        "declined' is CONTRADICTED (not ABSENT). Only use ABSENT when the "
        "sources genuinely neither confirm nor deny the assumed fact. Always "
        "check reported figures/totals/trends before deciding.\n\n"
        f"Question: {query}"
    )


def parse_presuppositions(text: str) -> list[Presupposition]:
    """Parse a JSON array of presuppositions from (possibly noisy) LLM output."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    raw = match.group(0) if match else text
    data = _loads_tolerant(raw)
    if not isinstance(data, list):
        return []
    out: list[Presupposition] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ptext = str(item.get("presupposition", "")).strip()
        if not ptext:
            continue
        status = str(item.get("status", "UNKNOWN")).strip().upper()
        if status not in ("SUPPORTED", "CONTRADICTED", "ABSENT"):
            status = "UNKNOWN"
        out.append(
            Presupposition(
                text=ptext,
                is_core=bool(item.get("is_core", False)),
                status=status,
            )
        )
    return out


def verdict_from_presuppositions(
    query: str, presuppositions: list[Presupposition]
) -> EpistemicVerdict:
    """Decide answerability from verified presuppositions (deterministic)."""
    # Drop meta/triviality presuppositions: data-reliability and completeness
    # assumptions that EVERY question implicitly makes and that should never, on
    # their own, render a question impossible. Without this guard the verifier
    # blocks ordinary questions on "the data is accurate and reliable".
    presuppositions = [
        p for p in presuppositions if not _META_PRESUPPOSITION_RE.search(p.text)
    ]
    core = [p for p in presuppositions if p.is_core]
    # A CONTRADICTED core presupposition => the question is built on a false
    # premise; answering it would validate the falsehood.
    contradicted_core = [p for p in core if p.status == "CONTRADICTED"]
    if contradicted_core:
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.FALSE_PREMISE,
            code=_CATEGORY_CODE[EpistemicCategory.FALSE_PREMISE],
            reason=(
                "The question rests on a premise the document contradicts. "
                "Answering it as posed would validate a false assumption; the "
                "premise must be corrected first."
            ),
            presuppositions=tuple(presuppositions),
            severity=Severity.VIOLATION,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.FALSE_PREMISE],
        )
    # An ABSENT core presupposition is UNCERTAINTY, not a proven violation. Per
    # the graded-execution contract we do NOT terminate on uncertainty: the
    # caller should run executable phases and report the maximum supported
    # conclusion plus a falsifier. We mark answerable=False (the question as
    # posed is not fully grounded) but severity=UNCERTAINTY so it does NOT
    # terminate the request.
    absent_core = [p for p in core if p.status == "ABSENT"]
    if absent_core:
        return EpistemicVerdict(
            answerable=False,
            category=EpistemicCategory.UNVERIFIABLE_PREMISE,
            code=_CATEGORY_CODE[EpistemicCategory.UNVERIFIABLE_PREMISE],
            reason=(
                "The question assumes something the document does not currently "
                "establish. This is uncertainty, not a proven impossibility — "
                "answerable sub-parts should still be executed, with the "
                "unsupported part flagged rather than the whole request refused."
            ),
            presuppositions=tuple(presuppositions),
            severity=Severity.UNCERTAINTY,
            falsifier=_CATEGORY_FALSIFIER[EpistemicCategory.UNVERIFIABLE_PREMISE],
        )
    return EpistemicVerdict(
        answerable=True,
        category=EpistemicCategory.ANSWERABLE,
        code=None,
        reason="No impossible-question pattern or false/unverifiable premise detected.",
        presuppositions=tuple(presuppositions),
        severity=Severity.UNCERTAINTY,
    )
