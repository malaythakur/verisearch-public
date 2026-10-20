"""Operational retrieval-stability measurement.

"Run N independent retrievals and check agreement" is meaningless without an
OPERATIONAL definition of (a) what makes two retrievals independent and (b) how
agreement is measured and thresholded. This module defines both concretely and
EXECUTES them, so retrieval stability is a measured fact rather than an assumed
or procedural claim.

Independence perturbations (each run varies the retrieval along one axis so the
runs are not trivially identical):
  - ORDER:        re-rank ties / shuffle equal-score candidates.
  - CHUNK:        shift passage/chunk boundaries (different windowing offset).
  - DECOMPOSITION: decompose the query into sub-queries and union the results.

Agreement metrics across the runs' top-k document sets:
  - set agreement: mean pairwise Jaccard overlap of the top-k doc-id sets.
  - rank agreement: mean pairwise Kendall-tau-like rank correlation over the
    docs common to both runs.

A retrieval set is STABLE iff both metrics meet their thresholds. The result is
a structured StabilityReport the synthesis layer consumes to decide whether the
retrieval-stability prerequisite is satisfied (enabling certification) — instead
of hard-coding stability_executed=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


# Stability thresholds (operational definition of "stable").
SET_AGREEMENT_THRESHOLD = 0.6      # mean pairwise Jaccard of top-k doc sets
RANK_AGREEMENT_THRESHOLD = 0.5     # mean pairwise rank correlation
VARIANCE_THRESHOLD = 0.10          # max allowed variance of pairwise set-agreement
DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievalRun:
    """One retrieval run under a named independence perturbation."""

    perturbation: str           # "order" | "chunk" | "decomposition"
    doc_ids: tuple[str, ...]    # ranked document ids (best first)
    seed: int = 0               # RNG/order seed used for this run (audit field)
    chunking_policy: str = "default"  # chunk-boundary policy for this run


@dataclass(frozen=True)
class StabilityReport:
    stable: bool
    set_agreement: float
    rank_agreement: float
    runs: int
    perturbations: tuple[str, ...]
    top_k: int
    set_threshold: float
    rank_threshold: float
    variance_threshold: float
    set_variance: float
    seeds: tuple[int, ...]
    chunking_policies: tuple[str, ...]
    detail: str
    # Execution artifact: the actual top-k doc-id list returned by each run.
    # Proves the runs were executed (not asserted) and lets an auditor recompute
    # the agreement metrics independently.
    run_doc_ids: tuple[tuple[str, ...], ...] = ()
    # Per-pair set-agreement (Jaccard) artifacts: [(run_i, run_j, jaccard), ...].
    pairwise_overlap: tuple[tuple[str, str, float], ...] = ()

    def to_dict(self) -> dict:
        return {
            "stable": self.stable,
            "set_agreement": round(self.set_agreement, 3),
            "rank_agreement": round(self.rank_agreement, 3),
            "set_variance": round(self.set_variance, 4),
            "runs": self.runs,
            "perturbations": list(self.perturbations),
            "top_k": self.top_k,
            # Full audit spec.
            "audit_spec": {
                "set_agreement_cutoff": self.set_threshold,
                "rank_agreement_cutoff": self.rank_threshold,
                "variance_threshold": self.variance_threshold,
                "seeds": list(self.seeds),
                "chunking_policies": list(self.chunking_policies),
            },
            # Execution artifacts (the actual retrieved doc-id lists per run +
            # the per-pair overlap values an auditor can recompute against).
            "artifacts": {
                "run_doc_ids": {
                    p: list(ids)
                    for p, ids in zip(self.perturbations, self.run_doc_ids)
                },
                "pairwise_overlap": list(self.pairwise_overlap),
            },
            "independence_note": (
                "Runs are perturbation-based approximations of independence "
                "(order / mode / query-decomposition); they are NOT guaranteed "
                "statistically independent samples. Agreement is measured, not "
                "assumed."
            ),
            "detail": self.detail,
        }


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


def _rank_agreement(a: list[str], b: list[str]) -> float:
    """Kendall-tau-like agreement over docs common to both rankings.

    Returns the fraction of concordant pairs among the common docs (1.0 = same
    relative order, 0.0 = fully reversed). Neutral (1.0) when fewer than two
    docs are common (no orderable information).
    """
    common = [d for d in a if d in set(b)]
    if len(common) < 2:
        return 1.0
    rank_b = {d: i for i, d in enumerate(b)}
    pairs = concordant = 0
    for x, y in combinations(common, 2):
        pairs += 1
        # x precedes y in `a` (by construction); concordant if also in `b`.
        if rank_b[x] < rank_b[y]:
            concordant += 1
    return concordant / pairs if pairs else 1.0


def measure_stability(
    runs: list[RetrievalRun],
    *,
    top_k: int = DEFAULT_TOP_K,
    set_threshold: float = SET_AGREEMENT_THRESHOLD,
    rank_threshold: float = RANK_AGREEMENT_THRESHOLD,
    variance_threshold: float = VARIANCE_THRESHOLD,
) -> StabilityReport:
    """Measure agreement across independent retrieval runs against thresholds."""
    seeds = tuple(r.seed for r in runs)
    policies = tuple(r.chunking_policy for r in runs)
    run_ids = tuple(r.doc_ids for r in runs)
    if len(runs) < 2:
        return StabilityReport(
            stable=False, set_agreement=0.0, rank_agreement=0.0,
            runs=len(runs), perturbations=tuple(r.perturbation for r in runs),
            top_k=top_k, set_threshold=set_threshold, rank_threshold=rank_threshold,
            variance_threshold=variance_threshold, set_variance=0.0,
            seeds=seeds, chunking_policies=policies, run_doc_ids=run_ids,
            detail="fewer than 2 independent runs; stability undefined.",
        )

    topk = [list(r.doc_ids[:top_k]) for r in runs]
    labels = [r.perturbation for r in runs]
    set_scores = [_jaccard(a, b) for a, b in combinations(topk, 2)]
    rank_scores = [_rank_agreement(a, b) for a, b in combinations(topk, 2)]
    pairwise = tuple(
        (labels[i], labels[j], round(_jaccard(topk[i], topk[j]), 3))
        for i, j in combinations(range(len(runs)), 2)
    )
    set_agreement = sum(set_scores) / len(set_scores)
    rank_agreement = sum(rank_scores) / len(rank_scores)
    # Variance of pairwise set-agreement — high variance means the runs
    # disagree inconsistently (some pairs agree, some don't), which is itself
    # an instability even if the mean clears the cutoff.
    mean_s = set_agreement
    set_variance = sum((s - mean_s) ** 2 for s in set_scores) / len(set_scores)

    stable = (
        set_agreement >= set_threshold
        and rank_agreement >= rank_threshold
        and set_variance <= variance_threshold
    )
    detail = (
        f"set_agreement {set_agreement:.2f} "
        f"({'>=' if set_agreement >= set_threshold else '<'} {set_threshold}); "
        f"rank_agreement {rank_agreement:.2f} "
        f"({'>=' if rank_agreement >= rank_threshold else '<'} {rank_threshold}); "
        f"set_variance {set_variance:.3f} "
        f"({'<=' if set_variance <= variance_threshold else '>'} {variance_threshold})"
    )
    return StabilityReport(
        stable=stable, set_agreement=set_agreement, rank_agreement=rank_agreement,
        runs=len(runs), perturbations=tuple(r.perturbation for r in runs),
        top_k=top_k, set_threshold=set_threshold, rank_threshold=rank_threshold,
        variance_threshold=variance_threshold, set_variance=set_variance,
        seeds=seeds, chunking_policies=policies, run_doc_ids=run_ids,
        pairwise_overlap=pairwise,
        detail=detail,
    )
