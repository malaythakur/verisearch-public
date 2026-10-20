"""Deterministic evidence-contract enforcement for the Answer Engine.

Some questions impose an explicit evidence contract, e.g. "build a
counterargument supported by BOTH a quantitative figure AND management
commentary". Prompt instructions alone do not reliably make a model TERMINATE
when the contract is unmet — it tends to admit the gap ("although there is no
direct management commentary...") and then produce a weakly-supported answer
anyway.

This module enforces the contract programmatically AFTER generation:

1. Parse the required evidence types from the query.
2. Detect, from the model's own answer text, which required types it admits are
   missing or that it tried to satisfy with an ineligible evidence class
   (a "schema leak", e.g. using Notes to the Financial Statements / footnotes /
   tables in place of management commentary).
3. If any required type is unsatisfied and the answer did not already terminate
   cleanly, OVERRIDE the answer with the correct abstention verdict.

This makes the contract a hard gate rather than a suggestion. It is conservative
(it only fires on explicit requirement language plus an explicit admission), so
it does not suppress legitimately-supported answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Evidence classes that DO count as "management commentary".
ALLOWED_COMMENTARY_SECTIONS = (
    "Letter to Shareholders",
    "Chairman's Letter",
    "CEO Letter",
    "Management's Discussion and Analysis",
    "Management Discussion and Analysis",
    "MD&A",
    "Business Review",
    "Management Commentary",
    "Management Overview",
)

# Evidence classes that do NOT count as management commentary (schema leak).
EXCLUDED_COMMENTARY_SECTIONS = (
    "Notes to Consolidated Financial Statements",
    "Notes to the Financial Statements",
    "Notes to Financial Statements",
    "Footnotes",
    "Tables",
)


@dataclass(frozen=True)
class ContractVerdict:
    """Outcome of evidence-contract enforcement."""

    enforced: bool                 # True if the answer was overridden.
    code: str | None               # Abstention code, e.g. NO_SUPPORTED_COUNTERARGUMENT.
    reason: str | None             # Human-readable reason.
    answer: str                    # The (possibly overridden) answer text.
    missing_types: tuple[str, ...] = ()


# --- Required-evidence parsing ------------------------------------------------

_REQUIRES_BOTH = re.compile(
    r"\bboth\b.*\band\b|\band\b.*\bmanagement\s+commentary\b", re.IGNORECASE
)
_REQ_MANAGEMENT = re.compile(
    r"management\s+(?:commentary|discussion|narrative)", re.IGNORECASE
)
_REQ_QUANTITATIVE = re.compile(
    r"\b(?:quantitative|numeric(?:al)?|figure|statistic|metric|number)\b",
    re.IGNORECASE,
)


def required_evidence_types(query: str) -> set[str]:
    """Return the set of evidence types the query explicitly requires."""
    q = query or ""
    required: set[str] = set()
    # Only treat evidence types as REQUIRED when the query frames them as a
    # support requirement ("supported by", "must include", "backed by", "both").
    requires_support = bool(
        re.search(
            r"support(?:ed)?\s+(?:by|with)|backed\s+by|must\s+(?:include|cite|use)|"
            r"\bboth\b|cite\s+(?:a|an|the)|grounded\s+in",
            q,
            re.IGNORECASE,
        )
    )
    if not requires_support:
        return required
    if _REQ_MANAGEMENT.search(q):
        required.add("management_commentary")
    if _REQ_QUANTITATIVE.search(q):
        required.add("quantitative")
    return required


# --- Admission detection ------------------------------------------------------

# The model conceding that management commentary is absent.
_NO_MGMT_COMMENTARY = re.compile(
    r"(?:no|without|lack(?:s|ing)?\s+(?:of\s+)?|absen(?:t|ce\s+of)|"
    r"do(?:es)?\s+not\s+(?:contain|include|provide|offer)\s+(?:any\s+|explicit\s+|direct\s+)?)"
    r"[^.]{0,40}?(?:direct\s+|explicit\s+|specific\s+)?management\s+"
    r"(?:commentary|discussion|narrative)",
    re.IGNORECASE,
)

# The model using an excluded section AS commentary (schema leak).
_COMMENTARY_SCHEMA_LEAK = re.compile(
    r"(?:notes\s+to\s+[^.]{0,40}financial\s+statements|footnotes?|"
    r"notes?\s+section)[^.]{0,60}(?:commentary|management|indicate|suggest|imply)",
    re.IGNORECASE,
)

# Quantitative absence admission (less common but symmetric).
_NO_QUANT = re.compile(
    r"(?:no|without|lack(?:s|ing)?\s+(?:of\s+)?|do(?:es)?\s+not\s+(?:contain|include|provide))"
    r"[^.]{0,40}?(?:quantitative|numeric(?:al)?|specific\s+figures?|specific\s+data)",
    re.IGNORECASE,
)

# A clean, final abstention already present in the answer.
_CLEAN_ABSTENTION = re.compile(
    r"no_supported_(?:answer|counterargument|argument)|not_determinable",
    re.IGNORECASE,
)


def _admits_missing(answer: str, required: set[str]) -> set[str]:
    """Return the required types the answer admits are missing/ineligible."""
    a = answer or ""
    missing: set[str] = set()
    if "management_commentary" in required:
        if _NO_MGMT_COMMENTARY.search(a) or _COMMENTARY_SCHEMA_LEAK.search(a):
            missing.add("management_commentary")
    if "quantitative" in required and _NO_QUANT.search(a):
        missing.add("quantitative")
    return missing


def _code_for_query(query: str) -> str:
    """Choose the abstention code matching the question's framing."""
    if re.search(r"counter\s*argument|counter-argument", query or "", re.IGNORECASE):
        return "NO_SUPPORTED_COUNTERARGUMENT"
    return "NO_SUPPORTED_ANSWER"


_TYPE_LABEL = {
    "management_commentary": "management commentary",
    "quantitative": "a quantitative figure",
}


def enforce_evidence_contract(query: str, answer: str) -> ContractVerdict:
    """Deterministically enforce the query's evidence contract on the answer.

    If the query requires evidence types that the answer itself admits are
    missing (or backed only by an ineligible section), and the answer did not
    already terminate with a clean abstention, the answer is overridden with the
    correct abstention verdict.
    """
    required = required_evidence_types(query)
    if not required:
        return ContractVerdict(False, None, None, answer)

    # If the model already produced a clean abstention AS ITS VERDICT and did not
    # then continue arguing, leave it alone.
    missing = _admits_missing(answer, required)
    if not missing:
        return ContractVerdict(False, None, None, answer)

    # The contract is violated. Even if the answer mentions the code somewhere,
    # if it also presented a substantive argument we override with a clean,
    # authoritative termination so the output cannot be read as a supported
    # answer.
    code = _code_for_query(query)
    missing_labels = ", ".join(sorted(_TYPE_LABEL.get(m, m) for m in missing))
    reason = (
        f"Required evidence not satisfied: {missing_labels}. "
        f"Per the question's contract, every candidate must be supported by "
        f"all required evidence types; eligible management commentary excludes "
        f"Notes to the Financial Statements, footnotes, and tables."
    )
    overridden = (
        f"{code}\n\n{reason}\n\n"
        f"No answer is produced because the evidence chain failed eligibility: "
        f"the sources do not provide {missing_labels} of the required class. "
        f"A disciplined abstention is the correct outcome here."
    )
    return ContractVerdict(
        enforced=True,
        code=code,
        reason=reason,
        answer=overridden,
        missing_types=tuple(sorted(missing)),
    )
