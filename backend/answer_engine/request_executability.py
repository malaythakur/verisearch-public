"""Request executability audit — is there an executable objective at all?

Before asking whether a question is ANSWERABLE from the document (adversarial
epistemology) or which conclusion is best (synthesis), a stronger system first
audits whether the REQUEST ITSELF is executable. These are distinct failures:

  - TASK_INCOMPLETE: there is no executable objective. A meta/optimization
    directive presupposes an object that does not exist — e.g. "minimize regret"
    needs an answer candidate (probability of error), an outcome definition
    (harm), and uncertainty over alternatives (information value). With no
    underlying question, none of those exist, so the task cannot be executed.
    The correct response is not "unverifiable" — it is to request the actual
    question.
  - UNDERDETERMINED: multiple valid outputs. A dangling referent with no
    antecedent ("compare them", "summarize it", "which is better?") admits many
    interpretations; the request must be disambiguated, not answered.
  - CONTRADICTORY: mutually exclusive constraints ("answer in one word but
    explain in detail", "list exactly 5 and exactly 10"). No output can satisfy
    all constraints simultaneously.
  - EXECUTABLE: a concrete, satisfiable objective — proceed.

This audit is deliberately FORM-level and deterministic: executability is a
property of the request's structure, not of the document. It is conservative
(it only fires on clear structural signals) so it never blocks an ordinary
question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    EXECUTABLE = "executable"
    TASK_INCOMPLETE = "task_incomplete"
    UNDERDETERMINED = "underdetermined"
    CONTRADICTORY = "contradictory"


_STATUS_CODE = {
    TaskStatus.TASK_INCOMPLETE: "TASK_INCOMPLETE",
    TaskStatus.UNDERDETERMINED: "UNDERDETERMINED",
    TaskStatus.CONTRADICTORY: "CONTRADICTORY_REQUEST",
}


@dataclass(frozen=True)
class ExecutabilityVerdict:
    executable: bool
    status: TaskStatus
    code: str | None
    reason: str
    missing: tuple[str, ...] = ()
    next_action: str | None = None

    def to_dict(self) -> dict:
        return {
            "executable": self.executable,
            "status": self.status.value,
            "code": self.code,
            "reason": self.reason,
            "missing": list(self.missing),
            "next_action": self.next_action,
        }

    def as_answer(self) -> str:
        lines = [self.code or "NON_EXECUTABLE_REQUEST", "", self.reason]
        if self.missing:
            lines.append("")
            lines.append("This task cannot be executed because it lacks:")
            for m in self.missing:
                lines.append(f"- {m}")
        if self.next_action:
            lines.append("")
            lines.append(f"Valid next action: {self.next_action}")
        return "\n".join(lines)


# --- TASK_INCOMPLETE: optimization/meta directive with no objective -----------

# Decision-theoretic / meta objects that are only meaningful relative to an
# existing answer or decision. Asking to optimize one of these with no
# underlying question means there is no object to optimize over.
_META_OBJECT_RE = re.compile(
    r"\b(?:regret|expected\s+(?:loss|value|utility|error)|"
    r"probability\s+of\s+(?:error|being\s+wrong)|information\s+(?:gain|value)|"
    r"utility|loss\s+function|risk(?:\s+function)?|the\s+answer|the\s+output|"
    r"the\s+response|the\s+result|the\s+conclusion)\b",
    re.IGNORECASE,
)
# Optimization / meta directives.
_OPTIMIZE_RE = re.compile(
    r"\b(?:minimi[sz]e|maximi[sz]e|optimi[sz]e|reduce|improve|refine|"
    r"enhance|tune|calibrate)\b",
    re.IGNORECASE,
)
# A concrete answerable target (a thing in the document) — its presence means
# the request DOES have an objective and is not task-incomplete.
_CONCRETE_TARGET_RE = re.compile(
    r"\b(?:revenue|income|profit|loss|asset|liabilit|equity|ratio|segment|"
    r"deposit|loan|capital|dividend|expense|tax|cost|share|employee|growth|"
    r"return|margin|conclusion\s+(?:from|about|regarding)|"
    r"document|report|section|page|table|figure|policy|risk\s+factor)\b",
    re.IGNORECASE,
)
# Interrogative markers — a real question target.
_INTERROGATIVE_RE = re.compile(
    r"\b(?:what|which|who|whom|when|where|why|how|whose|"
    r"list|summari[sz]e|compare|describe|explain|identify|find|show|"
    r"is|are|was|were|did|does|do|can|could)\b",
    re.IGNORECASE,
)


def _check_task_incomplete(query: str) -> ExecutabilityVerdict | None:
    q = query or ""
    has_optimize = bool(_OPTIMIZE_RE.search(q))
    has_meta_object = bool(_META_OBJECT_RE.search(q))
    has_concrete = bool(_CONCRETE_TARGET_RE.search(q))

    # A directive to optimize a decision-theoretic/meta object, with no concrete
    # answerable target, has no executable objective.
    if has_optimize and has_meta_object and not has_concrete:
        return ExecutabilityVerdict(
            executable=False,
            status=TaskStatus.TASK_INCOMPLETE,
            code=_STATUS_CODE[TaskStatus.TASK_INCOMPLETE],
            reason=(
                "This is a meta/optimization directive with no underlying "
                "question to operate on. The objective cannot be executed "
                "because it presupposes an answer that has not been posed."
            ),
            missing=(
                "an underlying question (the optimization has no object)",
                "an answer candidate (needed for probability-of-error / regret)",
                "an outcome definition (needed for harm/utility estimation)",
                "uncertainty over alternatives (needed for information value)",
            ),
            next_action="request the actual question to be answered.",
        )
    return None


# --- CONTRADICTORY: mutually exclusive constraints ----------------------------

_BREVITY_RE = re.compile(
    r"\bin\s+(?:one|a\s+single)\s+(?:word|sentence)\b|\bbriefly\b|"
    r"\bin\s+brief\b|\bone[- ]line\b|\btl;?dr\b|\bvery\s+short\b",
    re.IGNORECASE,
)
_VERBOSITY_RE = re.compile(
    r"\bin\s+(?:great\s+)?detail\b|\bin[- ]depth\b|\bcomprehensive(?:ly)?\b|"
    r"\bexhaustive(?:ly)?\b|\bat\s+length\b|\belaborate\b|\bthoroughly\b|"
    r"\bevery\s+detail\b|\bfully\s+explain\b",
    re.IGNORECASE,
)
_EXACT_COUNT_RE = re.compile(r"\bexactly\s+(\d+)\b", re.IGNORECASE)


def _check_contradictory(query: str) -> ExecutabilityVerdict | None:
    q = query or ""
    # Brevity + verbosity demanded together.
    if _BREVITY_RE.search(q) and _VERBOSITY_RE.search(q):
        return ExecutabilityVerdict(
            executable=False,
            status=TaskStatus.CONTRADICTORY,
            code=_STATUS_CODE[TaskStatus.CONTRADICTORY],
            reason=(
                "The request contains mutually exclusive constraints: it asks "
                "for both an extremely brief answer and an in-depth/detailed "
                "one. No single output can satisfy both at once."
            ),
            next_action="choose one level of detail and resubmit.",
        )
    # Two different exact counts for the same output.
    counts = {m.group(1) for m in _EXACT_COUNT_RE.finditer(q)}
    if len(counts) >= 2:
        return ExecutabilityVerdict(
            executable=False,
            status=TaskStatus.CONTRADICTORY,
            code=_STATUS_CODE[TaskStatus.CONTRADICTORY],
            reason=(
                "The request specifies two different exact counts "
                f"({', '.join(sorted(counts))}) for the same output, which "
                "cannot both be satisfied."
            ),
            next_action="specify a single required count.",
        )
    return None


# --- UNDERDETERMINED: dangling referent, no antecedent ------------------------

# A pronoun/demonstrative used as the object with no noun to bind it to.
_DANGLING_RE = re.compile(
    r"^\s*(?:please\s+)?(?:compare|summari[sz]e|rank|contrast|analy[sz]e|"
    r"evaluate|explain|describe|list)\s+"
    r"(?:them|it|these|those|that|this|the\s+(?:two|three|ones?|items?))\s*[.?]?\s*$",
    re.IGNORECASE,
)
_WHICH_BETTER_RE = re.compile(
    r"^\s*which\s+(?:one\s+)?is\s+(?:better|best|worse|the\s+best)\??\s*$",
    re.IGNORECASE,
)


def _check_underdetermined(query: str) -> ExecutabilityVerdict | None:
    q = (query or "").strip()
    if _DANGLING_RE.match(q) or _WHICH_BETTER_RE.match(q):
        return ExecutabilityVerdict(
            executable=False,
            status=TaskStatus.UNDERDETERMINED,
            code=_STATUS_CODE[TaskStatus.UNDERDETERMINED],
            reason=(
                "The request has a dangling referent with no antecedent (e.g. "
                "'compare them' / 'which is better') — it does not name the "
                "specific items to operate on, so it admits multiple valid "
                "interpretations."
            ),
            next_action="name the specific items or candidates to compare.",
        )
    return None


def assess_executability(query: str) -> ExecutabilityVerdict:
    """Audit whether the request has a single, satisfiable, executable objective.

    Order matters: contradictory constraints and missing-objective checks run
    before underdetermination. Returns an EXECUTABLE verdict when none fire.
    """
    for check in (_check_contradictory, _check_task_incomplete, _check_underdetermined):
        verdict = check(query)
        if verdict is not None:
            return verdict
    return ExecutabilityVerdict(
        executable=True,
        status=TaskStatus.EXECUTABLE,
        code=None,
        reason="The request has a concrete, satisfiable objective.",
    )
