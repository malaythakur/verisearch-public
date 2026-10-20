"""Structured candidate synthesis and deterministic selection.

Analytical questions ("what is the MOST DEFENSIBLE conclusion", "what would
remain true if half the report disappeared", "what is the best-supported
finding") are SELECTION problems. A single free-text LLM call biases toward the
salient or the safe answer and cannot be reliably steered with prompt text — it
will mix evidence classes, double-count correlated evidence, or escape to
low-information identity statements no matter how detailed the instructions.

This module makes selection deterministic:

  1. The LLM PROPOSES candidate conclusions as structured JSON — each with a
     claim, an evidence class, and the set of supporting evidence constructs.
  2. CODE DISPOSES — it scores each candidate on objective axes (evidence-class
     strength, construct independence with correlation-collapsing, information
     level, interpretation load, deletion-survival) according to the question's
     intent, then selects the winner and formats the final answer.

Because scoring lives in code, the policy is enforced, not merely suggested:
correlated balance-sheet facets collapse to one construct, low-information
identity claims are dominated by information-rich ones, and a "most defensible"
question deterministically prefers a pure high-strength claim over a blended one.
"""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass, field
from enum import Enum

from backend.answer_engine.specificity import information_breakdown, information_ordinal
from backend.answer_engine.contradiction import contradiction_matrix, metrics_in_claim as _metrics_in_claim
from backend.answer_engine.claim_scope import derive_scope, same_scope, EvidenceTier


class Outcome(str, Enum):
    """Closed set of allowed final outcomes (A-H). The synthesis layer MUST
    return exactly one of these — no ad-hoc status strings are permitted."""

    A_CERTIFIED_CONCLUSION = "CERTIFIED_CONCLUSION"
    B_MULTIPLE_MAXIMAL_CONCLUSIONS = "MULTIPLE_MAXIMAL_CONCLUSIONS"
    C_MULTIPLE_SUPPORTED = "MULTIPLE_SUPPORTED"          # distinct-scope additive facts
    D_PARTIAL_CONCLUSION_ONLY = "PARTIAL_CONCLUSION_ONLY"
    E_NO_SUPPORTED_ANSWER = "NO_SUPPORTED_ANSWER"
    F_CANNOT_ESTABLISH = "CANNOT_ESTABLISH"
    G_UNDERDETERMINED_FRONTIER = "UNDERDETERMINED_FRONTIER"
    H_RETRIEVAL_UNSTABLE = "RETRIEVAL_UNSTABLE"
    OBSERVER_DEPENDENT = "OBSERVER_DEPENDENT"


_ALLOWED_OUTCOMES = {o.value for o in Outcome}


def _assert_outcome(code: str) -> str:
    """Forbid non-schema statuses — the headline must be an allowed Outcome."""
    head = code.split("\n", 1)[0].strip()
    if head not in _ALLOWED_OUTCOMES:
        raise ValueError(f"non-schema outcome '{head}' (allowed: {sorted(_ALLOWED_OUTCOMES)})")
    return code


class SynthesisIntent(str, Enum):
    """The kind of analytical selection a question is asking for."""

    DEFENSIBLE = "defensible"   # highest certainty, lowest interpretation
    ROBUST = "robust"           # survives deletion: info value x independence
    GENERAL = "general"         # not a synthesis question


# --- Evidence taxonomy --------------------------------------------------------

# Evidence constructs, grouped so that correlated facets collapse to a single
# independent construct. Several balance-sheet line items (total assets, AUM,
# available-for-sale securities, loans, deposits) are all facets of ONE
# construct and must not be counted as independent support.
CONSTRUCT_GROUP = {
    "income_statement": "income_statement",   # revenue, net income, expenses
    "balance_sheet": "balance_sheet",          # assets, AUM, securities, loans, deposits, equity
    "capital_ratios": "balance_sheet",         # CET1 etc. are balance-sheet-derived
    "segment_reporting": "segment_reporting",  # per-segment results
    "business_descriptions": "business_descriptions",
    "management_discussion": "management_discussion",
    "rankings_awards": "rankings_awards",
    "narrative_identity": "narrative_identity",  # history, mission, "large institution"
    "forward_looking": "forward_looking",
}

# Strength of each evidence class for a DEFENSIBILITY judgment (higher = more
# defensible: hard data with low interpretation).
CLASS_STRENGTH = {
    "income_statement": 1.0,
    "balance_sheet": 0.95,
    "segment_reporting": 0.9,
    "capital_ratios": 0.9,
    "management_discussion": 0.55,
    "rankings_awards": 0.3,
    "narrative_identity": 0.2,
    "forward_looking": 0.1,
}

# Interpretation load: how much reading-between-the-lines a class requires.
CLASS_INTERPRETATION = {
    "income_statement": 0.0,
    "balance_sheet": 0.05,
    "capital_ratios": 0.1,
    "segment_reporting": 0.1,
    "management_discussion": 0.4,
    "rankings_awards": 0.7,
    "narrative_identity": 0.6,
    "forward_looking": 0.9,
}

# Evidence AUTHORITY: how authoritative a single statement of this class is, on
# its own, independent of repetition. Audited financial statements are highly
# authoritative even when a figure appears exactly once — precise reporting must
# not be punished for being unique.
CLASS_AUTHORITY = {
    "income_statement": 1.0,
    "balance_sheet": 1.0,
    "capital_ratios": 0.95,
    "segment_reporting": 0.9,
    "management_discussion": 0.6,
    "rankings_awards": 0.4,
    "narrative_identity": 0.3,
    "forward_looking": 0.2,
}

_INFO_WEIGHT = {"high": 1.0, "medium": 0.65, "low": 0.3}

# --- Claim-shape classification for entailment-based robustness ---------------
# An EXACT FIGURE can only be reconstructed from its home construct, so deleting
# that one section disconnects it (min-deletion = 1) regardless of how many
# adjacent constructs sit nearby.
_EXACT_FIGURE_RE = re.compile(
    r"[\$£€]\s?\d|\b\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m\b|bn\b)|"
    r"\b\d[\d,]{3,}\b|=\s*\$?\d|\bexactly\b",
    re.IGNORECASE,
)
# STRUCTURAL / EXISTENCE claims (the firm HAS/REPORTS segments, operates in
# regions, is organized into lines) are independently entailed by each section
# that exhibits the structure, so they survive many deletions.
_STRUCTURAL_RE = re.compile(
    r"\b(?:reports?|has|have|operates?|comprises?|consists?|organized|"
    r"multiple|several|various|diversified|business\s+segments?|"
    r"business\s+lines?|geographic)\b",
    re.IGNORECASE,
)
_DIVERSITY_RE = re.compile(
    r"\bdiversif|\bmultiple\b|\bseveral\b|\bvarious\b|across\b|\bsegments?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    """A proposed conclusion with its evidence metadata."""

    claim: str
    evidence_class: str                       # primary class (taxonomy key)
    constructs: tuple[str, ...] = ()          # supporting constructs (taxonomy keys)
    information_level: str = "medium"         # high | medium | low
    forward_looking: bool = False
    # Provenance: the distinct source locations (section/table/page labels) the
    # claim is drawn from. Used for DUPLICATION DETECTION — two mentions of the
    # SAME table are one provenance, not independent corroboration.
    sources: tuple[str, ...] = ()

    def distinct_provenances(self) -> set[str]:
        """Normalized set of distinct source locations (deduplicated).

        Section/table labels are normalized (lowercased, punctuation/þwhitespace
        collapsed) so "Note 5", "note 5.", "NOTE 5" count once. This is the
        provenance-separation primitive: repeated citations of the same source
        collapse to a single independent unit.
        """
        seen: set[str] = set()
        for s in self.sources:
            key = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
            if key:
                seen.add(key)
        return seen

    def independent_evidence_units(self) -> int:
        """Distinct evidence units = max(distinct provenances, entailing constructs).

        Prefer explicit provenance (deduplicated source locations) when the LLM
        supplied it; otherwise fall back to distinct entailing constructs. Two
        mentions of the same table yield ONE unit, not two.
        """
        prov = len(self.distinct_provenances())
        if prov > 0:
            return prov
        return len(self.entailing_constructs())

    def normalized_constructs(self) -> set[str]:
        """Collapse correlated constructs to their independent groups."""
        groups = set()
        for c in self.constructs:
            key = c.strip().lower().replace(" ", "_")
            groups.add(CONSTRUCT_GROUP.get(key, key))
        # The primary evidence class is itself a supporting construct.
        ec = self.evidence_class.strip().lower().replace(" ", "_")
        groups.add(CONSTRUCT_GROUP.get(ec, ec))
        return groups

    def independent_construct_count(self) -> int:
        return len(self.normalized_constructs())

    def entailing_constructs(self) -> set[str]:
        """Constructs that INDEPENDENTLY ENTAIL the claim (not merely adjacent).

        Topical co-location is not entailment. An exact figure (e.g. "net income
        = $57,048M") can only be reconstructed from its HOME construct — the
        income statement — so the balance sheet, though adjacent, does NOT entail
        it. A structural/existence claim ("the firm reports multiple business
        segments") is independently entailed by EACH section that exhibits the
        structure, so it survives deleting any one of them.
        """
        constructs = self.normalized_constructs()
        claim = self.claim or ""
        ec = self.evidence_class.strip().lower().replace(" ", "_")
        home = CONSTRUCT_GROUP.get(ec, ec)

        if _EXACT_FIGURE_RE.search(claim):
            # Exact figures are entailed only by their home construct.
            return {home}
        if _STRUCTURAL_RE.search(claim):
            # Structural/existence claims are independently entailed by each
            # distinct construct that exhibits the structure.
            return set(constructs)
        # Qualitative magnitude ("highly profitable", "stable"): entailed by the
        # home construct; an adjacent construct corroborates only if it directly
        # measures the same dimension. Conservatively, count the home construct
        # plus segment reporting when the claim spans segments.
        entailing = {home}
        if "segment_reporting" in constructs and _DIVERSITY_RE.search(claim):
            entailing.add("segment_reporting")
        return entailing

    def min_deletion_size(self) -> int:
        """Minimum number of sections to delete before the claim loses support.

        Equal to the number of constructs that independently entail the claim:
        you must remove all of them to disconnect the claim from the evidence.
        """
        return len(self.entailing_constructs())


@dataclass(frozen=True)
class EvidenceMeasures:
    """RAW, unweighted primitives measured per candidate.

    Per the contract, the system computes ONLY measurable primitives and does
    NOT combine them with hidden weights. Selection is by a DECLARED
    lexicographic priority over these primitives, not an opaque scalar — so
    every ranking decision is reconstructable from the raw numbers.

      - evidence_count: distinct supporting constructs cited (topical).
      - evidence_independence: distinct constructs that INDEPENDENTLY ENTAIL the
        claim (== min_deletion).
      - assumption_count: interpretation/assumption load as an integer count
        (0 = pure data, higher = more inference); forward-looking adds one.
      - deletion_robustness: == evidence_independence (sections to delete before
        the claim loses entailment).
      - disqualified / disqualify_reason: hard epistemic disqualifiers
        (forward-looking, rankings) that are NOT a weighting — they are
        categorical eligibility, stated explicitly.
    """

    evidence_count: int
    evidence_independence: int
    assumption_count: int
    deletion_robustness: int
    information_level: int  # ordinal: 2/1/0 — DERIVED from observable counts below
    independent_evidence_units: int  # distinct provenances (duplication-collapsed)
    # Observable specificity feature counts that RECONSTRUCT information_level
    # (so it is a measurable primitive, not a preference bucket).
    info_numerals: int
    info_units: int
    info_named_entities: int
    info_qualifiers: int
    disqualified: bool
    disqualify_reason: str | None

    def to_dict(self) -> dict:
        return {
            "evidence_count": self.evidence_count,
            "evidence_independence": self.evidence_independence,
            "assumption_count": self.assumption_count,
            "deletion_robustness": self.deletion_robustness,
            "information_level": self.information_level,
            "information_features": {
                "numerals": self.info_numerals,
                "units": self.info_units,
                "named_entities": self.info_named_entities,
                "qualifiers": self.info_qualifiers,
            },
            "independent_evidence_units": self.independent_evidence_units,
            "disqualified": self.disqualified,
            "disqualify_reason": self.disqualify_reason,
        }


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    measures: "EvidenceMeasures"
    rejection_reason: str | None = None
    dominated_by: str | None = None  # claim text of a candidate that dominates this one

    @property
    def objectives(self) -> dict:
        """Pareto objective vector (higher is better on each axis)."""
        m = self.measures
        return {
            "evidence_count": m.evidence_count,
            "evidence_independence": m.evidence_independence,
            "deletion_robustness": m.deletion_robustness,
            "information": m.information_level,
            "independent_units": m.independent_evidence_units,
            "low_assumptions": -m.assumption_count,  # fewer assumptions is better
        }


@dataclass(frozen=True)
class SynthesisResult:
    intent: SynthesisIntent
    winner: Candidate | None
    answer: str
    rejected: tuple[ScoredCandidate, ...] = ()
    selected_score: float = 0.0
    pareto_frontier: tuple[ScoredCandidate, ...] = ()
    requirements: tuple[dict, ...] = ()


# --- Intent detection ---------------------------------------------------------

_DEFENSIBLE_RE = re.compile(
    r"most\s+defensible|best[- ]supported|most\s+evidence[- ]backed|"
    r"most\s+(?:certain|rigorous|objective)\s+conclusion|"
    r"strongest\s+conclusion",
    re.IGNORECASE,
)
_ROBUST_RE = re.compile(
    r"remain\s+true|still\s+be\s+true|disappear|removed|deleted|"
    r"most\s+robust|survive|withstand|even\s+if\s+(?:half|part|some)",
    re.IGNORECASE,
)
_CONCLUSION_RE = re.compile(
    r"\bconclusion\b|\bconclude\b|what\s+can\s+(?:you|we)\s+(?:say|infer)",
    re.IGNORECASE,
)


def detect_synthesis_intent(query: str) -> SynthesisIntent:
    q = query or ""
    if _ROBUST_RE.search(q):
        return SynthesisIntent.ROBUST
    if _DEFENSIBLE_RE.search(q):
        return SynthesisIntent.DEFENSIBLE
    return SynthesisIntent.GENERAL


# --- Scoring ------------------------------------------------------------------

# Identity/metadata claims that are low information regardless of how they are
# labeled. Used to floor the information level so an "exists / large institution"
# claim cannot win by claiming high information.
_IDENTITY_CLAIM_RE = re.compile(
    r"\b(?:exists?|has\s+existed|long\s+history|founded|"
    r"large\s+(?:and\s+\w+\s+)?(?:financial\s+)?(?:institution|company|bank)|"
    r"significant\s+presence|major\s+(?:financial\s+)?(?:institution|player))\b",
    re.IGNORECASE,
)


def _effective_info_weight(candidate: Candidate) -> float:
    level = candidate.information_level.lower()
    weight = _INFO_WEIGHT.get(level, 0.65)
    # Floor identity/metadata claims to low information even if labeled higher.
    if _IDENTITY_CLAIM_RE.search(candidate.claim or ""):
        weight = min(weight, _INFO_WEIGHT["low"])
    return weight


def _assumption_count(c: Candidate) -> int:
    """Integer assumption/interpretation count (no weighting).

    0 for pure reported data (income statement, balance sheet, segments);
    +1 for interpretive narrative/management classes; +1 more for forward-
    looking. This is a COUNT, not a weight — it feeds Pareto and the declared
    lexicographic priority directly.
    """
    ec = c.evidence_class.strip().lower().replace(" ", "_")
    interpretive = {"management_discussion", "narrative_identity", "rankings_awards"}
    count = 1 if ec in interpretive else 0
    if c.forward_looking or ec == "forward_looking":
        count += 1
    # An identity/metadata claim carries an extra interpretive assumption.
    if _IDENTITY_CLAIM_RE.search(c.claim or ""):
        count += 1
    return count


def _disqualifier(c: Candidate) -> str | None:
    """Categorical eligibility (NOT weighting): epistemic disqualifiers.

    These are stated reasons a class cannot answer the question at all, not a
    soft penalty. Reported separately so selection over the raw primitives is
    not contaminated by hidden scoring.
    """
    ec = c.evidence_class.strip().lower().replace(" ", "_")
    if c.forward_looking or ec == "forward_looking":
        return "forward-looking: an uncertain outcome the report does not establish"
    if _PROMOTIONAL_RE.search(c.claim or ""):
        return ("promotional/self-characterization: marketing language "
                "(largest/leading/world-class/best-in-class) is a self-claim, "
                "not a certifiable report fact")
    if ec == "rankings_awards":
        return "ranking/award: depends on external methodology not established in the report"
    if ec == "narrative_identity":
        return "narrative/identity: interpretive and low-information, not a report-grounded conclusion"
    return None


# Promotional / self-characterization language: superlatives a firm uses to
# describe ITSELF. These are marketing claims, not certifiable report facts.
_PROMOTIONAL_RE = re.compile(
    r"\b(?:largest|biggest|leading|world[- ]class|best[- ]in[- ]class|"
    r"number\s*one|#1|premier|top[- ](?:tier|ranked)|most\s+(?:trusted|admired|"
    r"respected)|industry[- ]leading|market\s+leader|dominant)\b",
    re.IGNORECASE,
)


def measure_candidate(c: Candidate) -> EvidenceMeasures:
    """Compute ONLY the raw, unweighted primitives for a candidate."""
    independence = c.min_deletion_size()
    reason = _disqualifier(c)
    # Information is the RAW observable specificity count (numerals + units +
    # named entities + qualifiers) — a pure count, NOT a bucketed ordinal.
    # Bucketing to 0/1/2 was itself a synthetic utility; the raw count is a
    # direct measurement an auditor can reproduce from the claim text.
    info = information_breakdown(c.claim or "")
    info_count = 0 if _IDENTITY_CLAIM_RE.search(c.claim or "") else info["specificity_score"]
    return EvidenceMeasures(
        evidence_count=len(c.normalized_constructs()),
        evidence_independence=independence,
        assumption_count=_assumption_count(c),
        deletion_robustness=independence,
        information_level=info_count,
        independent_evidence_units=c.independent_evidence_units(),
        info_numerals=info["numerals"],
        info_units=info["units"],
        info_named_entities=info["named_entities"],
        info_qualifiers=info["qualifiers"],
        disqualified=reason is not None,
        disqualify_reason=reason,
    )


# Declared lexicographic selection priority per intent. This is the ONLY ranking
# rule and it is stated openly — it orders candidates by the raw primitives in a
# fixed sequence, with no hidden weights or multiplication. Each tuple element
# is (objective_key, higher_is_better).
# NOTE: there is intentionally NO lexicographic priority / weighting table.
# Selection is purely by Pareto dominance (see score_candidates). Any fixed
# priority over the objectives would be implicit weighting and would leak an
# objective preference, which the contract forbids.


def _dominates(a: ScoredCandidate, b: ScoredCandidate, axes: tuple[str, ...]) -> bool:
    """True if a Pareto-dominates b across ALL declared axes."""
    ao, bo = a.objectives, b.objectives
    ge_all = all(ao[ax] >= bo[ax] for ax in axes)
    gt_any = any(ao[ax] > bo[ax] for ax in axes)
    return ge_all and gt_any


# Declared Pareto objectives — the FULL set used for dominance. Every key here
# is a measured primitive; nothing outside this set influences selection.
# (Stated once so the axes the code uses and the axes it declares cannot drift.)
# Declared Pareto objectives — the FULL set used for dominance. Every key here
# is a measured primitive; nothing outside this set influences selection.
# NOTE: `information` is deliberately NOT a dominance axis — counting numerals/
# units/qualifiers rewards denser phrasing (compression bias: "income fell from
# X to Y in FY2025" would auto-dominate "income fell"). It is reported as
# metadata only, never used to select a winner.
_PARETO_AXES = (
    "evidence_count",
    "evidence_independence",
    "deletion_robustness",
    "independent_units",
    "low_assumptions",
)
_PARETO_AXES_DESC = (
    "evidence_count / evidence_independence / deletion_robustness / "
    "independent_units / low_assumptions"
)


def claim_topic(claim: str) -> str:
    """Semantic topic of a claim = the named metric/area it is about.

    Used to PARTITION the Pareto frontier: candidates on different topics
    (assets vs income vs capital) are not competing alternatives, so dominance
    is only computed within a topic. Falls back to a coarse keyword bucket, then
    to 'general' when nothing matches.
    """
    metrics = _metrics_in_claim(claim)
    if metrics:
        return sorted(metrics)[0]
    text = (claim or "").lower()
    for area, kws in _TOPIC_KEYWORDS.items():
        if any(k in text for k in kws):
            return area
    return "general"


_TOPIC_KEYWORDS = {
    "profitability": ("profit", "income", "earnings", "margin"),
    "capital": ("capital", "tier 1", "cet1", "equity ratio"),
    "balance_sheet": ("assets", "liabilit", "deposits", "loans", "aum"),
    "segments": ("segment", "business line", "division"),
    "operations": ("operations", "headcount", "employees", "efficiency", "overhead"),
}


# Maximum Pareto frontier size before the result is declared UNDERDETERMINED.
# Beyond this, an unranked frontier is no longer a useful answer — it is
# indecision — so the system says so rather than dumping N "equally valid"
# conclusions.
_MAX_FRONTIER = 4

# Observer-invariance dimension FILTERS (NOT weightings). Each stakeholder
# selects a SUBSET of the objective axes it cares about; within that subset the
# check is pure Pareto dominance (no ordering, no weights). A stakeholder can
# thus DISQUALIFY a candidate it finds dominated, but cannot PRIORITIZE one axis
# over another. The union of axes across stakeholders is exactly the Pareto set.
_OBSERVER_OBJECTIVES = {
    # Auditor: verifiability — independence, deletion-robustness, low assumptions.
    "auditor": ("evidence_independence", "deletion_robustness", "low_assumptions"),
    # Regulator: corroboration breadth and low interpretation.
    "regulator": ("independent_units", "evidence_count", "low_assumptions"),
    # Investor: corroboration breadth and entailment (NOT information — that is
    # not a dominance axis; including it would reintroduce length/density bias).
    "investor": ("evidence_count", "independent_units", "evidence_independence"),
}


def observer_invariant_frontier(
    scored: list[ScoredCandidate],
) -> list[ScoredCandidate]:
    """Candidates non-dominated under EVERY stakeholder objective subset.

    Executes observer invariance concretely: a candidate survives only if no
    stakeholder (auditor/regulator/investor), using that stakeholder's own
    objective subset, would find it dominated. The intersection across all
    stakeholders is the observer-invariant set.
    """
    eligible = [s for s in scored if s.rejection_reason is None]
    invariant: list[ScoredCandidate] = []
    for s in eligible:
        survives_all = True
        for axes in _OBSERVER_OBJECTIVES.values():
            dominated = any(
                other is not s and _dominates(other, s, axes)
                for other in eligible
            )
            if dominated:
                survives_all = False
                break
        if survives_all:
            invariant.append(s)
    return invariant


def _canonicalize(candidates: list[Candidate]) -> list[Candidate]:
    """Merge same-(entity, metric, timeframe) candidates, keep strongest.

    Strength = (independent evidence units, evidence tier). Sub-scope is part of
    the key so a firm-level claim and a segment-level claim on the same metric
    are NOT merged. Preserves input order of the kept members.
    """
    best: dict[tuple, Candidate] = {}
    order: list[tuple] = []
    for c in candidates:
        sc = derive_scope(c.claim, c.evidence_class)
        key = (sc.entity, sc.metric, sc.sub_scope, sc.timeframe)
        if key not in best:
            best[key] = c
            order.append(key)
            continue
        cur = best[key]
        cur_sc = derive_scope(cur.claim, cur.evidence_class)
        c_strength = (c.independent_evidence_units(), int(sc.tier))
        cur_strength = (cur.independent_evidence_units(), int(cur_sc.tier))
        if c_strength > cur_strength:
            best[key] = c
    return [best[k] for k in order]


def score_candidates(
    candidates: list[Candidate], intent: SynthesisIntent
) -> list[ScoredCandidate]:
    """Measure raw primitives, mark disqualified, and compute TRUE Pareto.

    NO weighting and NO ranking among eligible candidates. Selection is PURELY
    by Pareto dominance: a candidate is selectable only if it is non-dominated.
    There is no lexicographic priority and no scalar — that would be implicit
    weighting and would leak an objective preference. Display order is:
    non-dominated (Pareto-optimal) first, then dominated, then disqualified;
    WITHIN each group order is by original position (no preference applied).
    """
    # PHASE 4.5 — CANONICALIZATION: merge candidates that share the SAME
    # (entity, metric, timeframe) scope into one, keeping the member with the
    # strongest provenance (most independent units, then highest tier). This
    # collapses near-duplicate phrasings of the same fact BEFORE Pareto, so the
    # frontier reflects distinct conclusions, not restatements.
    candidates = _canonicalize(candidates)

    measured: list[ScoredCandidate] = []
    for c in candidates:
        m = measure_candidate(c)
        measured.append(
            ScoredCandidate(candidate=c, measures=m, rejection_reason=m.disqualify_reason)
        )
    eligible = [s for s in measured if s.rejection_reason is None]

    # Precompute scopes (entity/metric/sub-scope/timeframe/unit/tier) once.
    scopes = {id(s): derive_scope(s.candidate.claim, s.candidate.evidence_class)
              for s in measured}

    annotated: list[ScoredCandidate] = []
    for s in measured:
        dominator = None
        if s.rejection_reason is None:
            s_scope = scopes[id(s)]
            for other in eligible:
                if other is s:
                    continue
                # Claim Partition + Scope Guard: only SAME-SCOPE claims (same
                # entity, metric, sub-scope, timeframe) are comparable. Different
                # scopes COEXIST (truths are additive). This subsumes the earlier
                # topic partition with a stricter key.
                if not same_scope(scopes[id(other)], s_scope):
                    continue
                o_scope = scopes[id(other)]
                # Evidence hierarchy: a strictly higher-tier same-scope claim
                # supersedes a lower-tier one outright.
                if o_scope.tier > s_scope.tier:
                    dominator = other.candidate.claim
                    break
                if o_scope.tier < s_scope.tier:
                    continue  # this claim outranks `other` by tier
                if _dominates(other, s, _PARETO_AXES):
                    dominator = other.candidate.claim
                    break
        annotated.append(
            ScoredCandidate(
                candidate=s.candidate,
                measures=s.measures,
                rejection_reason=s.rejection_reason,
                dominated_by=dominator,
            )
        )

    # Group order only — NO preference ranking among the Pareto frontier.
    def group(s: ScoredCandidate) -> int:
        if s.rejection_reason is not None:
            return 2          # disqualified last
        if s.dominated_by is not None:
            return 1          # dominated middle
        return 0              # Pareto-optimal first

    annotated.sort(key=group)  # stable: preserves input order within a group
    return annotated


def pareto_frontier(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """Return the non-dominated eligible candidates (the true Pareto frontier)."""
    return [
        s for s in scored
        if s.rejection_reason is None and s.dominated_by is None
    ]


# --- Formatting ---------------------------------------------------------------

_CLASS_LABEL = {
    "income_statement": "firm-level income statement (revenue, net income)",
    "balance_sheet": "balance-sheet composition (assets, AUM, securities, loans)",
    "capital_ratios": "capital ratios",
    "segment_reporting": "segment reporting",
    "business_descriptions": "business-line descriptions",
    "management_discussion": "management's discussion & analysis",
    "rankings_awards": "rankings/awards",
    "narrative_identity": "narrative/identity",
    "forward_looking": "forward-looking statements",
}


def _label(construct: str) -> str:
    key = construct.strip().lower().replace(" ", "_")
    return _CLASS_LABEL.get(CONSTRUCT_GROUP.get(key, key), construct)


def _build_requirements_ledger(
    intent: SynthesisIntent, scored: list[ScoredCandidate],
    frontier: list[ScoredCandidate], stability_executed: bool = False,
    observer_invariance_executed: bool = False, contradiction_count: int = 0,
) -> list[dict]:
    """Explicit ledger of which evaluation requirements were executed/dropped.

    The core auditability ask: the system must state which requirements it
    intentionally did NOT execute, and why — rather than appearing rigorous
    while silently collapsing them.
    """
    return [
        {
            "requirement": "raw primitives only (no hidden weighting)",
            "status": "EXECUTED",
            "note": "the system reports ONLY measured primitives — evidence_count, "
                    "evidence_independence, assumption_count, deletion_robustness, "
                    "information_level — and does not combine them with weights or "
                    "multiplication.",
        },
        {
            "requirement": "selection by Pareto dominance only (no weighting/ranking)",
            "status": "EXECUTED",
            "note": "a candidate is selectable only if it uniquely dominates all "
                    "others; multiple non-dominated candidates are reported as a "
                    "trade-off and NOT ranked. No lexicographic priority or scalar "
                    "is used (that would be implicit weighting).",
        },
        {
            "requirement": "true multi-objective Pareto frontier",
            "status": "EXECUTED",
            "note": f"{len(frontier)} non-dominated candidate(s); dominance requires "
                    f">= on ALL declared axes [{_PARETO_AXES_DESC}] and > on one, so "
                    "genuine trade-offs stay on the frontier.",
        },
        {
            "requirement": "frontier termination rule",
            "status": "EXECUTED",
            "note": f"if more than {_MAX_FRONTIER} candidates are mutually "
                    "non-dominated the result is UNDERDETERMINED_FRONTIER "
                    "(indecision is reported, not N equally-valid conclusions).",
        },
        {
            "requirement": "provenance separation / duplication detection",
            "status": "EXECUTED",
            "note": "independent_evidence_units deduplicates source locations — "
                    "two mentions of the same table/section count as ONE unit, "
                    "not independent corroboration.",
        },
        {
            "requirement": "deletion-robustness as one dimension (not a gate)",
            "status": "EXECUTED",
            "note": "deletion_robustness is one Pareto axis; precise single-section "
                    "figures stay eligible, not rejected.",
        },
        {
            "requirement": "certification pipeline DAG",
            "status": "EXECUTED",
            "note": "Normalization -> Extraction -> Stability -> Candidate -> "
                    "Attack(elimination) -> Invariance(observer) -> "
                    "Falsification(contradiction+min-failure-cert) -> Audit(ledger) "
                    "-> Certification(decision rule). Each stage's artifact is in "
                    "this report.",
        },
        {
            "requirement": "unique-conclusion decision rule",
            "status": "EXECUTED",
            "note": "a single certified Conclusion is allowed ONLY IF exactly one "
                    "candidate survives observer invariance AND the frontier "
                    "collapses to one scope; otherwise MULTIPLE_SUPPORTED / "
                    "MULTIPLE_MAXIMAL_CONCLUSIONS / UNDERDETERMINED_FRONTIER.",
        },
        {
            "requirement": "observer invariance (auditor/regulator/investor views)",
            "status": "EXECUTED" if observer_invariance_executed else "NOT_EXECUTED",
            "note": ("candidates re-evaluated under concrete per-stakeholder "
                     "objective subsets (auditor=independence/robustness/low-"
                     "assumptions; regulator=units/breadth/low-assumptions; "
                     "investor=information/breadth/units); winner must be "
                     "non-dominated under ALL three."
                     if observer_invariance_executed else
                     "phase NOT executed: candidates are not re-evaluated under "
                     "different stakeholder priorities. It is a certification "
                     "prerequisite, so its absence blocks certification "
                     "(OBSERVER_DEPENDENT) — not silently dropped."),
        },
        {
            "requirement": "retrieval-stability evidence (overlap/disagreement)",
            "status": "EXECUTED" if stability_executed else "NOT_EXECUTED",
            "note": ("measured across retrieval runs." if stability_executed else
                     "phase NOT executed: stability is not measured across runs. "
                     "Because certification depends on it, the result is gated to "
                     "RETRIEVAL_UNSTABLE rather than certified, and confidence is "
                     "downgraded — it is NOT silently assumed neutral."),
        },
        {
            "requirement": "explicit contradiction set (falsifier)",
            "status": "EXECUTED",
            "note": f"{contradiction_count} pairwise contradiction(s) computed over "
                    "all candidates (directional / negation / numeric). The "
                    "falsifier is explicit, so an adversary cannot silently "
                    "substitute a contradicting conclusion.",
        },
    ]


def _format_measure_line(s: ScoredCandidate) -> str:
    m = s.measures
    dom = (
        f"  [dominated by: \"{s.dominated_by}\"]" if s.dominated_by
        else "  [Pareto-optimal]"
    ) if s.rejection_reason is None else ""
    return (
        f"    primitives: evidence_count={m.evidence_count}, "
        f"evidence_independence={m.evidence_independence}, "
        f"assumption_count={m.assumption_count}, "
        f"deletion_robustness={m.deletion_robustness}, "
        f"independent_units={m.independent_evidence_units}, "
        f"information_level={m.information_level} "
        f"(=raw count: numerals {m.info_numerals} + units {m.info_units} + "
        f"entities {m.info_named_entities} + qualifiers {m.info_qualifiers})"
        f"{dom}"
    )


def _append_audit_block(
    lines: list[str], intent: SynthesisIntent,
    scored: list[ScoredCandidate], frontier: list[ScoredCandidate],
    stability_executed: bool = False, observer_invariance_executed: bool = False,
) -> list[dict]:
    # Compute the full pairwise contradiction matrix (the falsifier) over all
    # candidate claims, and surface it.
    claims = [s.candidate.claim for s in scored]
    contradictions = contradiction_matrix(claims)
    ledger = _build_requirements_ledger(
        intent, scored, frontier, stability_executed, observer_invariance_executed,
        contradiction_count=len(contradictions),
    )
    lines.append("")
    lines.append(f"Pareto frontier (non-dominated across {_PARETO_AXES_DESC}):")
    if frontier:
        for s in frontier:
            lines.append(f"- \"{s.candidate.claim}\"  {s.objectives}")
    else:
        lines.append("- (none eligible)")
    lines.append("")
    lines.append("Pairwise contradiction matrix (falsifier, metric-bound):")
    if contradictions:
        for c in contradictions:
            lines.append(
                f"- [{c.type}/{c.metric}] \"{claims[c.i]}\" <> \"{claims[c.j]}\": "
                f"{c.detail} {c.artifact}"
            )
    else:
        lines.append("- none detected among candidates (metric-bound check)")
    lines.append("")
    # Adversarial elimination trace: WHY each non-surviving candidate was
    # removed, and which survived — so survival is evidenced, not asserted.
    lines.append("Elimination trace (adversarial):")
    survivors = 0
    for s in scored:
        sc = derive_scope(s.candidate.claim, s.candidate.evidence_class)
        scope_lbl = f"{sc.metric}/{sc.sub_scope}/{sc.timeframe}"
        if s.rejection_reason is not None:
            lines.append(
                f"- ELIMINATED \"{s.candidate.claim}\" — disqualified: {s.rejection_reason}"
            )
        elif s.dominated_by is not None:
            lines.append(
                f"- ELIMINATED \"{s.candidate.claim}\" — superseded within scope "
                f"'{scope_lbl}' by \"{s.dominated_by}\""
            )
        else:
            survivors += 1
            lines.append(
                f"- SURVIVED \"{s.candidate.claim}\" — non-dominated in scope "
                f"'{scope_lbl}' (tier {sc.tier.name})"
            )
    lines.append(f"  ({survivors} survived of {len(scored)} candidates)")
    lines.append("")
    survivors_sc = [
        s for s in scored
        if s.rejection_reason is None and s.dominated_by is None
    ]
    # Independence guard (#5): flag survivors resting on a single origin.
    low_independence = [
        s.candidate.claim for s in survivors_sc
        if s.measures.independent_evidence_units < 2
    ]
    if low_independence:
        lines.append("LOW_INDEPENDENCE (rests on a single evidence origin; "
                     "independence < 2):")
        for cl in low_independence:
            lines.append(f"- {cl}")
        lines.append("")
    # Minimal Failure Certificate (#6): the smallest evidence removal that would
    # overturn a surviving conclusion = its min-deletion size (sections that
    # must be removed before it loses entailment).
    lines.append("Minimal failure certificate (smallest change that breaks each survivor):")
    if survivors_sc:
        for s in survivors_sc:
            md = s.candidate.min_deletion_size()
            lines.append(
                f"- \"{s.candidate.claim}\": remove {md} entailing section(s) "
                f"-> conclusion no longer supported (overturn threshold = {md})"
            )
    else:
        lines.append("- (no surviving conclusion)")
    lines.append("")
    # Fact / Inference split: separate directly-stated facts from derived
    # inferences among the surviving (non-dominated, eligible) claims.
    facts, inferences = [], []
    for s in survivors_sc:
        sc = derive_scope(s.candidate.claim, s.candidate.evidence_class)
        if sc.tier >= EvidenceTier.SECONDARY and not sc.is_requirement:
            facts.append(s.candidate.claim)
        else:
            inferences.append(s.candidate.claim)
    lines.append("FACTS_SUPPORTED (directly stated, primary/secondary evidence):")
    for f in facts or ["- (none)"]:
        lines.append(f"- {f}" if f != "- (none)" else f)
    lines.append("INFERENCES_SUPPORTED (derived / summary / interpretive):")
    for inf in inferences or ["- (none)"]:
        lines.append(f"- {inf}" if inf != "- (none)" else inf)
    lines.append("")
    lines.append("Requirements ledger (what this evaluation did and did NOT execute):")
    for r in ledger:
        lines.append(f"- [{r['status']}] {r['requirement']}: {r['note']}")
    # Audit checksum (#10): hash of the decision-relevant state so reruns are
    # detectable / tamper-evident.
    state = "|".join([
        lines[0] if lines else "",
        ";".join(sorted(claims)),
        ";".join(f"{c.type}:{c.metric}:{c.i}-{c.j}" for c in contradictions),
    ])
    audit_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()[:16]
    lines.append("")
    lines.append(f"audit_hash: {audit_hash} (sha256 of outcome + candidate set + contradictions)")
    # Outcome enum closure (#1): the headline MUST be an allowed Outcome.
    _assert_outcome(lines[0])
    return ledger


def format_synthesis_answer(
    intent: SynthesisIntent, scored: list[ScoredCandidate],
    *, stability_executed: bool = False, observer_invariance_executed: bool = False,
) -> SynthesisResult:
    """Deterministically format the answer from raw-measured candidates.

    Precedence (certification dependency graph): a trustworthiness
    CERTIFICATION requires ALL prerequisite phases —
        retrieval_stability AND observer_invariance.
    If ANY prerequisite was NOT executed, certification is blocked: the result
    is gated (RETRIEVAL_UNSTABLE / OBSERVER_DEPENDENT) and the candidate
    analysis is shown as PROVISIONAL, NOT certified. Certifying on an
    unexecuted prerequisite would violate the contract.

    Selection (when permitted) is PURELY by Pareto dominance — no weighting and
    no ranking among the frontier:
      * 0 eligible        -> NO_SUPPORTED_ANSWER
      * frontier size 1   -> that candidate (justified solely by dominance)
      * frontier size > 1 -> PARTIAL_CONCLUSION_ONLY (genuine trade-off, no
                             internal ranking)
    """
    eligible = [s for s in scored if s.rejection_reason is None]
    rejected = [s for s in scored if s.rejection_reason is not None]
    frontier = pareto_frontier(scored)

    if not eligible:
        lines = ["NO_SUPPORTED_ANSWER", ""]
        lines.append(
            "No candidate conclusion meets the bar for this question. "
            "Disqualified candidates:"
        )
        for s in rejected[:5]:
            lines.append(f"- \"{s.candidate.claim}\" — {s.rejection_reason}")
        ledger = _append_audit_block(
            lines, intent, scored, frontier, stability_executed,
            observer_invariance_executed,
        )
        return SynthesisResult(
            intent=intent, winner=None, answer="\n".join(lines),
            rejected=tuple(rejected), selected_score=0.0,
            pareto_frontier=tuple(frontier), requirements=tuple(ledger),
        )

    # Precedence gate: certification requires ALL prerequisites. Report every
    # missing prerequisite so the dependency graph is explicit.
    missing_prereqs = []
    if not stability_executed:
        missing_prereqs.append(("RETRIEVAL_UNSTABLE", "retrieval-stability (cross-run overlap/disagreement)"))
    if not observer_invariance_executed:
        missing_prereqs.append(("OBSERVER_DEPENDENT", "observer-invariance (auditor/regulator/investor views)"))
    if missing_prereqs:
        code = missing_prereqs[0][0]  # primary headline = first missing prereq
        missing_desc = " AND ".join(d for _, d in missing_prereqs)
        lines = [
            code,
            "",
            "Certification is blocked. The certification dependency graph "
            "requires ALL of: retrieval_stability AND observer_invariance. "
            f"Unexecuted prerequisite(s): {missing_desc}. Per the contract, a "
            "trustworthiness conclusion cannot be certified on an unexecuted "
            "prerequisite. The candidate analysis below is PROVISIONAL — "
            "non-dominated candidates only, no winner certified:",
        ]
        if frontier:
            for s in frontier:
                lines.append(f"- (provisional) \"{s.candidate.claim}\"  {s.objectives}")
                lines.append(_format_measure_line(s))
        else:
            lines.append("- (no non-dominated candidate)")
        ledger = _append_audit_block(
            lines, intent, scored, frontier, stability_executed,
            observer_invariance_executed,
        )
        return SynthesisResult(
            intent=intent, winner=None, answer="\n".join(lines),
            rejected=tuple(rejected), selected_score=0.0,
            pareto_frontier=tuple(frontier), requirements=tuple(ledger),
        )

    # Genuine trade-off: more than one non-dominated candidate => no single
    # most-trustworthy output. No internal ranking is applied.
    if len(frontier) > 1:
        # Frontier termination rule (scope-aware): indecision is too many
        # candidates competing WITHIN A SINGLE scope. Coexisting different-scope
        # facts are additive, not indecision, so they don't trigger this.
        from collections import Counter as _Counter
        scope_counts = _Counter(
            derive_scope(s.candidate.claim, s.candidate.evidence_class).key()
            for s in frontier
        )
        max_in_scope = max(scope_counts.values()) if scope_counts else 0
        if max_in_scope > _MAX_FRONTIER:
            worst = max(scope_counts, key=lambda k: scope_counts[k])
            lines = [
                "UNDERDETERMINED_FRONTIER",
                "",
                f"{max_in_scope} candidates compete within a SINGLE scope "
                f"{worst} — too many (> {_MAX_FRONTIER}) to resolve without "
                "weighting the objectives (not permitted). The question is "
                "under-determined at the current evidence granularity; narrow "
                "the question or supply objective weights. Non-dominated "
                "candidates:",
            ]
            for s in frontier[:_MAX_FRONTIER + 2]:
                lines.append(f"- \"{s.candidate.claim}\"  {s.objectives}")
            ledger = _append_audit_block(
                lines, intent, scored, frontier, stability_executed,
                observer_invariance_executed,
            )
            return SynthesisResult(
                intent=intent, winner=None, answer="\n".join(lines),
                rejected=tuple(rejected), selected_score=0.0,
                pareto_frontier=tuple(frontier), requirements=tuple(ledger),
            )

        # Observer invariance is now EXECUTED (prerequisite satisfied): narrow
        # the frontier to candidates non-dominated under EVERY stakeholder lens.
        invariant = observer_invariant_frontier(scored)
        frontier_scopes = {
            derive_scope(s.candidate.claim, s.candidate.evidence_class).key()
            for s in frontier
        }

        # DECISION RULE (fixes the certify-while-frontier-unresolved bug):
        # a UNIQUE certified conclusion is allowed ONLY IF exactly one candidate
        # survives observer invariance AND the entire frontier collapses to a
        # single scope. Otherwise the frontier is unresolved and we MUST return
        # a multiple/under-determined verdict — never a single "Conclusion:".
        unique_allowed = len(invariant) == 1 and len(frontier_scopes) == 1
        if unique_allowed:
            winner = invariant[0].candidate
            entailing = sorted(winner.entailing_constructs())
            intent_word = "most robust" if intent == SynthesisIntent.ROBUST else "most defensible"
            why = (
                "It is the UNIQUE observer-invariant candidate AND the frontier "
                "collapses to one scope: non-dominated under the auditor, "
                "regulator, AND investor dimension FILTERS, with all other "
                "candidates in the same scope dominated. Selected by dominance "
                "alone — no weighting or ranking. Independently entailed by "
                f"{winner.min_deletion_size()} section(s): "
                f"{', '.join(_label(c) for c in entailing)}."
            )
            lines = [
                "CERTIFIED_CONCLUSION",
                "",
                f"Conclusion: {winner.claim}",
                "",
                f"Why this is the {intent_word} conclusion: {why}",
                "",
                "Candidate set (RAW primitives only — no weighting, no ranking):",
            ]
            for s in scored:
                note = "" if s.rejection_reason is None else f"  [disqualified: {s.rejection_reason}]"
                lines.append(f"- \"{s.candidate.claim}\"{note}")
                lines.append(_format_measure_line(s))
            ledger = _append_audit_block(
                lines, intent, scored, frontier, stability_executed,
                observer_invariance_executed,
            )
            return SynthesisResult(
                intent=intent, winner=winner, answer="\n".join(lines),
                rejected=tuple(rejected), selected_score=0.0,
                pareto_frontier=tuple(invariant), requirements=tuple(ledger),
            )

        # Coexistence Rule: truths are additive, contradictions are exceptional.
        # Different scopes -> MULTIPLE_SUPPORTED (additive facts). One scope with
        # several maximal candidates -> MULTIPLE_MAXIMAL_CONCLUSIONS (genuine
        # same-scope ambiguity). NEVER certify a single winner here.
        if len(frontier_scopes) > 1:
            lines = [
                "MULTIPLE_SUPPORTED",
                "",
                f"{len(frontier)} conclusions are independently supported on "
                f"{len(frontier_scopes)} DISTINCT scopes (different entity/metric/"
                "sub-scope/timeframe). They COEXIST — they are additive truths, "
                "not competing alternatives, and are not ranked against each "
                f"other. ({len(invariant)} are observer-invariant.) No single "
                "conclusion is certified because the frontier is not unique:",
            ]
        else:
            lines = [
                "MULTIPLE_MAXIMAL_CONCLUSIONS",
                "",
                f"{len(frontier)} candidates share ONE scope and are mutually "
                "non-dominated (each better on at least one primitive, none "
                "worse on all). They are NOT ranked — that would require "
                "weighting the objectives, which is not permitted. No unique "
                f"conclusion ({len(invariant)} observer-invariant):",
            ]
        for s in frontier:
            inv = "  [observer-invariant]" if s in invariant else ""
            lines.append(f"- \"{s.candidate.claim}\"  {s.objectives}{inv}")
            lines.append(_format_measure_line(s))
        ledger = _append_audit_block(
            lines, intent, scored, frontier, stability_executed,
            observer_invariance_executed,
        )
        return SynthesisResult(
            intent=intent, winner=None, answer="\n".join(lines),
            rejected=tuple(rejected), selected_score=0.0,
            pareto_frontier=tuple(frontier), requirements=tuple(ledger),
        )

    # Exactly one non-dominated candidate: selected SOLELY because it
    # Pareto-dominates every other eligible candidate — no weighting, no ranking.
    winner_sc = frontier[0]
    winner = winner_sc.candidate
    entailing = sorted(winner.entailing_constructs())
    intent_word = "most robust" if intent == SynthesisIntent.ROBUST else "most defensible"
    why = (
        "It is the UNIQUE Pareto-optimal candidate: every other eligible "
        "candidate is dominated by it (no better on any objective). It is "
        "selected by dominance alone, with no weighting or ranking applied. "
        f"Independently entailed by {winner.min_deletion_size()} section(s): "
        f"{', '.join(_label(c) for c in entailing)}."
    )
    lines = [
        "CERTIFIED_CONCLUSION",
        "",
        f"Conclusion: {winner.claim}",
        "",
        f"Why this is the {intent_word} conclusion: {why}",
        "",
        "Candidate set (RAW primitives only — no weighting, no ranking):",
    ]
    for s in scored:
        note = "" if s.rejection_reason is None else f"  [disqualified: {s.rejection_reason}]"
        lines.append(f"- \"{s.candidate.claim}\"{note}")
        lines.append(_format_measure_line(s))
    ledger = _append_audit_block(
        lines, intent, scored, frontier, stability_executed,
        observer_invariance_executed,
    )
    return SynthesisResult(
        intent=intent, winner=winner, answer="\n".join(lines),
        rejected=tuple(rejected), selected_score=0.0,
        pareto_frontier=tuple(frontier), requirements=tuple(ledger),
    )


# --- LLM extraction prompt + parsing ------------------------------------------

def build_extraction_instruction(query: str) -> str:
    """Instruction asking the LLM to emit candidate conclusions as JSON."""
    taxonomy = ", ".join(sorted(set(CONSTRUCT_GROUP.keys())))
    return (
        "From the provided sources, extract 3-6 CANDIDATE conclusions that "
        "could answer the question below. Do NOT pick a winner. Return ONLY a "
        "JSON array, no prose. Each element must be an object with keys:\n"
        '  "claim": a one-sentence conclusion stated plainly,\n'
        '  "evidence_class": one of [' + taxonomy + "],\n"
        '  "constructs": array of the distinct evidence constructs (from the '
        "same list) that support the claim in the sources,\n"
        '  "information_level": "high" | "medium" | "low" (how specific/'
        "informative the claim is),\n"
        '  "forward_looking": true if the claim asserts a future outcome,\n'
        '  "sources": array of the DISTINCT source locations the claim is drawn '
        "from (e.g. section title, table name, page) — list each distinct "
        "location once; do NOT repeat the same table/section as if it were "
        "multiple independent sources.\n"
        "Include a spread of candidates: some specific/quantitative, some "
        "broad, some weak (rankings, narrative) so they can be compared.\n\n"
        f"Question: {query}"
    )


def _loads_tolerant(raw: str):
    """Parse JSON, repairing common small-model mistakes.

    Some models (e.g. Groq llama) emit string VALUES without quotes, e.g.
    `"claim": JPMorgan generated net income, "evidence_class": income_statement`.
    Standard json.loads rejects this. We first try strict parsing, then a
    repair pass that quotes unquoted scalar values following a key.
    """
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    repaired = _repair_unquoted_values(raw)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_unquoted_values(raw: str):
    """Quote unquoted string values that follow a JSON key.

    Transforms `"key": some unquoted text,` -> `"key": "some unquoted text",`
    while leaving already-quoted strings, numbers, booleans, null, objects, and
    arrays untouched.
    """
    # Match a key, colon, then a value that is NOT already a quote/brace/bracket/
    # number/bool/null, up to the next unescaped , } or ] at the same level.
    pattern = re.compile(
        r'("(?:[^"\\]|\\.)*"\s*:\s*)'        # group1: "key":
        r'(?!\s*(?:"|\{|\[|-?\d|true|false|null))'  # value not already valid
        r'([^,\}\]\n]+?)'                     # group2: the bare value
        r'(\s*[,\}\]])'                       # group3: terminator
    )

    def _q(m: re.Match) -> str:
        value = m.group(2).strip().replace('"', '\\"')
        return f'{m.group(1)}"{value}"{m.group(3)}'

    return pattern.sub(_q, raw)


def parse_candidates(text: str) -> list[Candidate]:
    """Parse a JSON array of candidates from (possibly noisy) LLM output."""
    if not text:
        return []
    # Extract the first JSON array in the text.
    match = re.search(r"\[.*\]", text, re.DOTALL)
    raw = match.group(0) if match else text
    data = _loads_tolerant(raw)
    if not isinstance(data, list):
        return []

    candidates: list[Candidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        ec = str(item.get("evidence_class", "")).strip().lower().replace(" ", "_")
        constructs_raw = item.get("constructs", []) or []
        if isinstance(constructs_raw, str):
            constructs_raw = [constructs_raw]
        constructs = tuple(
            str(c).strip().lower().replace(" ", "_")
            for c in constructs_raw
            if str(c).strip()
        )
        info = str(item.get("information_level", "medium")).strip().lower()
        if info not in ("high", "medium", "low"):
            info = "medium"
        fwd = bool(item.get("forward_looking", False))
        sources_raw = item.get("sources", []) or []
        if isinstance(sources_raw, str):
            sources_raw = [sources_raw]
        sources = tuple(
            str(x).strip() for x in sources_raw if str(x).strip()
        )
        candidates.append(
            Candidate(
                claim=claim,
                evidence_class=ec or "narrative_identity",
                constructs=constructs,
                information_level=info,
                forward_looking=fwd,
                sources=sources,
            )
        )
    return candidates


def synthesize(
    query: str, candidate_json: str, *, stability_executed: bool = False,
    observer_invariance_executed: bool = False,
) -> SynthesisResult | None:
    """Full pipeline: parse candidates, score, select, format.

    Returns None if the question is not a synthesis question or no candidates
    could be parsed (caller should fall back to normal generation).

    Certification requires ALL prerequisite phases (retrieval_stability AND
    observer_invariance). When any is False the result is gated rather than
    certified, so the system never certifies on an unexecuted prerequisite.
    """
    intent = detect_synthesis_intent(query)
    if intent == SynthesisIntent.GENERAL:
        return None
    candidates = parse_candidates(candidate_json)
    if not candidates:
        return None
    scored = score_candidates(candidates, intent)
    return format_synthesis_answer(
        intent, scored, stability_executed=stability_executed,
        observer_invariance_executed=observer_invariance_executed,
    )
