"""Bayesian confidence calibration with monotonic update rules.

Earlier the system "downgraded confidence" by ad-hoc capping. This module gives
confidence an explicit posterior P(H|E) and monotonic update rules, so the
number is a defined probability rather than a heuristic.

Model: the hypothesis H = "the produced conclusion is correct/trustworthy".
Start from a prior and apply independent evidence factors as likelihood ratios
in log-odds space (Bayesian update). Each factor moves the posterior
MONOTONICALLY in a stated direction:

  - corroboration  (more independent evidence units)        -> raises P(H|E)
  - entailment     (higher deletion-robustness/independence) -> raises P(H|E)
  - retrieval stability measured & stable                    -> raises P(H|E)
  - assumptions / interpretation load                        -> lowers P(H|E)
  - unexecuted prerequisite (stability/observer)             -> lowers P(H|E)
  - hedged / abstained answer                                -> lowers P(H|E)

Monotonicity is a property we can test: adding a positive factor never lowers
the posterior, and adding a negative factor never raises it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

_PRIOR = 0.5  # uninformative prior on conclusion correctness


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class EvidenceFactors:
    """Observable inputs to the posterior (all measured upstream)."""

    independent_units: int = 1          # corroboration breadth (deduped sources)
    entailment: int = 1                 # min-deletion / independence
    assumption_count: int = 0           # interpretation load
    stability_measured: bool = False
    stability_stable: bool = False
    prerequisites_satisfied: bool = False  # all certification prereqs executed
    hedged: bool = False
    abstained: bool = False


@dataclass(frozen=True)
class CalibrationReport:
    prior: float
    posterior: float
    log_odds_terms: tuple[tuple[str, float], ...]

    def to_dict(self) -> dict:
        return {
            "prior": round(self.prior, 4),
            "posterior": round(self.posterior, 4),
            "P(H|E)": round(self.posterior, 4),
            "log_odds_terms": [
                {"factor": name, "delta_log_odds": round(v, 4)}
                for name, v in self.log_odds_terms
            ],
        }


# Per-factor log-likelihood-ratio weights. Signs encode the monotonic direction;
# magnitudes are fixed constants (not tuned per-question), so the update is
# transparent and reproducible.
_W_UNIT = 0.40           # per independent unit beyond the first
_W_ENTAILMENT = 0.35     # per entailing section beyond the first
_W_ASSUMPTION = -0.55    # per assumption
_W_STABILITY_STABLE = 1.0
_W_STABILITY_UNSTABLE = -1.0
_W_PREREQ_MISSING = -1.2
_W_HEDGED = -0.8
_W_ABSTAINED = -1.5


def confidence_label(posterior: float, stability_stable: bool, prerequisites_satisfied: bool) -> str:
    """Map the posterior to a qualitative calibration band (not a raw number).

    DIRECT  — high posterior, prerequisites satisfied, stable retrieval.
    STRONG  — high posterior but a prerequisite/stability caveat.
    WEAK    — low posterior (assumptions/abstention dominate).
    UNSTABLE— retrieval not stable or a prerequisite unexecuted.
    """
    if not prerequisites_satisfied or not stability_stable:
        return "UNSTABLE"
    if posterior >= 0.75:
        return "DIRECT"
    if posterior >= 0.55:
        return "STRONG"
    return "WEAK"


def update_posterior(factors: EvidenceFactors, prior: float = _PRIOR) -> CalibrationReport:
    """Compute P(H|E) by monotonic Bayesian update in log-odds space."""
    terms: list[tuple[str, float]] = []

    u = _W_UNIT * max(0, factors.independent_units - 1)
    if u:
        terms.append(("corroboration(units)", u))
    e = _W_ENTAILMENT * max(0, factors.entailment - 1)
    if e:
        terms.append(("entailment", e))
    a = _W_ASSUMPTION * max(0, factors.assumption_count)
    if a:
        terms.append(("assumptions", a))

    if factors.stability_measured:
        s = _W_STABILITY_STABLE if factors.stability_stable else _W_STABILITY_UNSTABLE
        terms.append(("retrieval_stability", s))
    if not factors.prerequisites_satisfied:
        terms.append(("prerequisite_unexecuted", _W_PREREQ_MISSING))
    if factors.hedged:
        terms.append(("hedged", _W_HEDGED))
    if factors.abstained:
        terms.append(("abstained", _W_ABSTAINED))

    log_odds = _logit(prior) + sum(v for _, v in terms)
    posterior = _sigmoid(log_odds)
    return CalibrationReport(prior=prior, posterior=posterior, log_odds_terms=tuple(terms))
