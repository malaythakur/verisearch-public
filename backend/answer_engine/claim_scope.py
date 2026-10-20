"""Claim scope + evidence hierarchy — the compatibility-safe audit primitives.

Most audit refinements reduce to one idea: a claim is only COMPARABLE to
another when they share the same SCOPE. Scope = (entity, metric, sub-scope,
timeframe, unit). Two claims on different scopes COEXIST (truths are additive);
only same-scope claims can dominate or contradict each other (contradictions are
exceptional).

Also defines the EVIDENCE HIERARCHY: PRIMARY > SECONDARY > DERIVED > SUMMARY.
When two same-scope claims conflict, the higher tier survives.

All of this is parsed from OBSERVABLE text features (regex over the claim and
its declared evidence class), so it adds metadata without changing the existing
Pareto/measurement machinery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from backend.answer_engine.contradiction import metrics_in_claim


class EvidenceTier(IntEnum):
    """Higher tier survives a same-scope conflict."""

    PRIMARY = 4     # audited financial statements / direct reported figures
    SECONDARY = 3   # segment reporting, notes
    DERIVED = 2     # ratios/계산 derived from primaries (ROE, margins)
    SUMMARY = 1     # MD&A narrative, highlights summaries
    UNKNOWN = 0


_TIER_BY_CLASS = {
    "income_statement": EvidenceTier.PRIMARY,
    "balance_sheet": EvidenceTier.PRIMARY,
    "segment_reporting": EvidenceTier.SECONDARY,
    "capital_ratios": EvidenceTier.DERIVED,
    "management_discussion": EvidenceTier.SUMMARY,
    "rankings_awards": EvidenceTier.SUMMARY,
    "narrative_identity": EvidenceTier.SUMMARY,
    "forward_looking": EvidenceTier.SUMMARY,
}

# Derived-metric signals (ratios computed from primaries).
_DERIVED_METRIC_RE = re.compile(
    r"\b(?:ratio|return on|roe|rotce|margin|per share|eps|yield|rate)\b",
    re.IGNORECASE,
)

# Timeframe extraction (observable).
_YEAR_RE = re.compile(r"\b(20\d\d)\b")
_TIMEFRAME_RE = re.compile(
    r"\b(?:fy\s*20\d\d|q[1-4]\s*20\d\d|over the past \w+ years?|"
    r"year[- ]over[- ]year|since 20\d\d|in 20\d\d|three years?|annual)\b",
    re.IGNORECASE,
)

# Unit extraction (observable).
_UNIT_RE = re.compile(r"(%|\$|€|£|percent|million|billion|bps|per share)", re.IGNORECASE)

# Requirement vs observation: a requirement/normative statement is NOT an
# observation and must not contradict an observation.
_REQUIREMENT_RE = re.compile(
    r"\b(?:must|should|shall|required|requirement|policy|mandate|"
    r"is\s+expected\s+to|needs?\s+to|target(?:s|ed)?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimScope:
    entity: str
    metric: str
    sub_scope: str       # e.g. a segment name, or "firm"
    timeframe: str
    unit: str
    tier: EvidenceTier
    is_requirement: bool

    def key(self) -> tuple[str, str, str, str]:
        """Comparability key — claims are comparable iff their keys match."""
        return (self.entity, self.metric, self.sub_scope, self.timeframe)

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "metric": self.metric,
            "sub_scope": self.sub_scope,
            "timeframe": self.timeframe,
            "unit": self.unit,
            "tier": self.tier.name,
            "is_requirement": self.is_requirement,
        }


_SEGMENT_RE = re.compile(
    r"\b(consumer\s*&?\s*community\s+banking|commercial\s*&?\s*investment\s+bank|"
    r"asset\s*&?\s*wealth\s+management|corporate)\b",
    re.IGNORECASE,
)


def derive_scope(claim: str, evidence_class: str, entity: str = "firm") -> ClaimScope:
    """Derive a ClaimScope from observable features of the claim + its class."""
    text = claim or ""
    metrics = metrics_in_claim(text)
    metric = sorted(metrics)[0] if metrics else "general"

    seg = _SEGMENT_RE.search(text)
    sub_scope = seg.group(0).lower().strip() if seg else "firm"

    tf = _TIMEFRAME_RE.search(text)
    if tf:
        timeframe = tf.group(0).lower().strip()
    else:
        ys = _YEAR_RE.findall(text)
        timeframe = ys[0] if ys else "unspecified"

    unit_m = _UNIT_RE.search(text)
    unit = unit_m.group(0).lower() if unit_m else "none"

    ec = (evidence_class or "").strip().lower().replace(" ", "_")
    tier = _TIER_BY_CLASS.get(ec, EvidenceTier.UNKNOWN)
    # A ratio/derived metric overrides class-based tier to DERIVED.
    if _DERIVED_METRIC_RE.search(text) and tier > EvidenceTier.DERIVED:
        tier = EvidenceTier.DERIVED

    is_requirement = bool(_REQUIREMENT_RE.search(text))

    return ClaimScope(
        entity=entity, metric=metric, sub_scope=sub_scope,
        timeframe=timeframe, unit=unit, tier=tier, is_requirement=is_requirement,
    )


def same_scope(a: ClaimScope, b: ClaimScope) -> bool:
    """Two claims are comparable iff entity+metric+sub_scope+timeframe match."""
    return a.key() == b.key()
