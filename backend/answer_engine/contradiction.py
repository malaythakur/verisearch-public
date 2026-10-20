"""Pairwise contradiction matrix — metric-bound, artifact-emitting.

A trustworthy synthesis must show which conclusions CONTRADICT each other so an
adversary cannot replace the chosen conclusion with an equally-"supported"
opposite. The contradiction must be METRIC-BOUND: two claims contradict only
when they make OPPOSING statements about the SAME metric/quantity. Different
metrics moving differently (assets up, net income down) is NOT a contradiction.

Each detected contradiction carries the artifact that proves it (the shared
metric and the two conflicting values/directions), so the falsifier is
evidence, not assertion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INCREASE = re.compile(r"\b(?:increas\w*|grew|grow\w*|rose|rising|rise|up|higher|gain\w*|improv\w*|stronger)\b", re.IGNORECASE)
_DECREASE = re.compile(r"\b(?:decreas\w*|fell|fall\w*|declin\w*|dropp?\w*|down|lower|loss\w*|worsen\w*|reduc\w*|weaker)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:no|not|never|without|fail\w*|absence|did\s+not|does\s+not|cannot)\b", re.IGNORECASE)
_REQUIREMENT_RE = re.compile(
    r"\b(?:must|should|shall|required|requirement|policy|mandate|"
    r"expected\s+to|needs?\s+to|target(?:s|ed)?|minimum|maximum|at\s+least|"
    r"no\s+more\s+than)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\$?\b\d[\d,]*(?:\.\d+)?\b%?")

# Named financial METRICS. Two claims can only contradict if they refer to the
# SAME metric — this is what makes the matrix metric-bound rather than
# subject-bound (the earlier false-positive: assets vs net income share the word
# "company" but are different metrics).
_METRICS = {
    "net income": r"net\s+income",
    "net revenue": r"(?:total\s+)?(?:net\s+)?revenue",
    "total assets": r"total\s+assets|assets",
    "deposits": r"deposits",
    "loans": r"loans",
    "roe": r"return\s+on\s+(?:common\s+)?equity|\broe\b|rotce",
    "cet1": r"common\s+equity\s+tier\s*1|cet1|tier\s*1\s+capital",
    "eps": r"earnings\s+per\s+share|\beps\b",
    "expense": r"noninterest\s+expense|expenses?",
    "dividend": r"dividend",
    "book value": r"book\s+value",
    "headcount": r"employees?|headcount",
    "stock price": r"share\s+price|stock\s+price",
}
_METRIC_RE = {k: re.compile(v, re.IGNORECASE) for k, v in _METRICS.items()}


@dataclass(frozen=True)
class Contradiction:
    i: int
    j: int
    type: str          # "directional" | "negation" | "numeric"
    metric: str        # the shared metric the contradiction is bound to
    detail: str
    artifact: dict     # the proving evidence (values/directions per claim)

    def to_dict(self) -> dict:
        return {
            "i": self.i, "j": self.j, "type": self.type,
            "metric": self.metric, "detail": self.detail, "artifact": self.artifact,
        }


def _metrics_in(claim: str) -> set[str]:
    return {m for m, rx in _METRIC_RE.items() if rx.search(claim or "")}


def metrics_in_claim(claim: str) -> set[str]:
    """Public: the set of named metrics a claim refers to (for topic partition)."""
    return _metrics_in(claim)


def _numbers(claim: str) -> list[float]:
    out = []
    for m in _NUMBER.findall(claim or ""):
        try:
            out.append(float(m.replace("$", "").replace(",", "").replace("%", "")))
        except ValueError:
            continue
    return out


def detect_contradiction(a: str, b: str) -> Contradiction | None:
    """Return a metric-bound Contradiction if a and b conflict, else None.

    Semantic guards (compatibility-safe):
      - same metric required (metric-bound);
      - a REQUIREMENT/normative statement does not contradict an OBSERVATION
        ("ratio must exceed 10%" vs "ratio was 14.6%" is not a conflict);
      - contradiction requires incompatible VALUE/direction, not mere
        co-occurrence.
    """
    shared = _metrics_in(a) & _metrics_in(b)
    if not shared:
        return None  # no shared METRIC -> cannot contradict (metric-bound)
    metric = sorted(shared)[0]

    # Requirement vs observation are different speech acts — not a contradiction.
    a_req, b_req = bool(_REQUIREMENT_RE.search(a)), bool(_REQUIREMENT_RE.search(b))
    if a_req != b_req:
        return None

    a_inc, a_dec = bool(_INCREASE.search(a)), bool(_DECREASE.search(a))
    b_inc, b_dec = bool(_INCREASE.search(b)), bool(_DECREASE.search(b))
    if (a_inc and b_dec and not a_dec) or (a_dec and b_inc and not b_dec):
        return Contradiction(
            i=-1, j=-1, type="directional", metric=metric,
            detail=f"opposing trend for '{metric}'",
            artifact={"a_direction": "up" if a_inc else "down",
                      "b_direction": "up" if b_inc else "down"},
        )

    a_neg, b_neg = bool(_NEGATION.search(a)), bool(_NEGATION.search(b))
    if a_neg != b_neg:
        return Contradiction(
            i=-1, j=-1, type="negation", metric=metric,
            detail=f"one claim negates the other for '{metric}'",
            artifact={"a_negates": a_neg, "b_negates": b_neg},
        )

    na, nb = _numbers(a), _numbers(b)
    if na and nb:
        big_a, big_b = max(na), max(nb)
        denom = max(abs(big_a), abs(big_b), 1.0)
        if abs(big_a - big_b) / denom > 0.05:
            return Contradiction(
                i=-1, j=-1, type="numeric", metric=metric,
                detail=f"differing figures for '{metric}'",
                artifact={"a_value": big_a, "b_value": big_b},
            )
    return None


def contradiction_matrix(claims: list[str]) -> list[Contradiction]:
    """Full pairwise, METRIC-BOUND contradiction matrix (the falsifier)."""
    out: list[Contradiction] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            hit = detect_contradiction(claims[i], claims[j])
            if hit:
                out.append(Contradiction(
                    i=i, j=j, type=hit.type, metric=hit.metric,
                    detail=hit.detail, artifact=hit.artifact,
                ))
    return out
