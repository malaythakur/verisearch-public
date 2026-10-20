"""Tests for the operational/formal definitions: retrieval stability,
observable information specificity, and Bayesian confidence calibration."""

import math

from backend.answer_engine.retrieval_stability import (
    RetrievalRun,
    measure_stability,
)
from backend.answer_engine.specificity import (
    information_ordinal,
    specificity_features,
    specificity_score,
)
from backend.answer_engine.calibration import (
    EvidenceFactors,
    update_posterior,
)


# --- Retrieval stability ------------------------------------------------------

def test_identical_runs_are_stable():
    runs = [
        RetrievalRun("order", ("a", "b", "c", "d", "e")),
        RetrievalRun("chunk", ("a", "b", "c", "d", "e")),
        RetrievalRun("decomposition", ("a", "b", "c", "d", "e")),
    ]
    report = measure_stability(runs)
    assert report.stable
    assert report.set_agreement == 1.0
    assert report.rank_agreement == 1.0


def test_disjoint_runs_are_unstable():
    runs = [
        RetrievalRun("order", ("a", "b", "c")),
        RetrievalRun("chunk", ("x", "y", "z")),
    ]
    report = measure_stability(runs)
    assert not report.stable
    assert report.set_agreement == 0.0


def test_single_run_is_undefined_unstable():
    report = measure_stability([RetrievalRun("order", ("a", "b"))])
    assert not report.stable
    assert "fewer than 2" in report.detail


def test_reordered_runs_lower_rank_agreement():
    runs = [
        RetrievalRun("order", ("a", "b", "c", "d")),
        RetrievalRun("chunk", ("d", "c", "b", "a")),  # fully reversed
    ]
    report = measure_stability(runs)
    # Same set (Jaccard 1.0) but reversed order -> rank agreement 0.
    assert report.set_agreement == 1.0
    assert report.rank_agreement == 0.0
    assert not report.stable


# --- Observable information specificity ---------------------------------------

def test_specificity_is_observable_and_deterministic():
    claim = "Net income was $57,048 million in 2025, up 12% year over year."
    f = specificity_features(claim)
    assert f["numerals"] >= 2
    assert f["units"] >= 1
    # Deterministic: same input -> same score.
    assert specificity_score(claim) == specificity_score(claim)
    assert information_ordinal(claim) == 2


def test_generic_claim_has_low_information():
    assert information_ordinal("The company exists and operates.") == 0


def test_information_ordinal_buckets():
    assert information_ordinal("Revenue grew.") in (0, 1)
    assert information_ordinal("Revenue was $182,447M in 2025 vs $177,556M in 2024.") == 2


# --- Bayesian calibration -----------------------------------------------------

def test_posterior_is_probability():
    r = update_posterior(EvidenceFactors())
    assert 0.0 <= r.posterior <= 1.0
    assert "P(H|E)" in r.to_dict()


def test_more_corroboration_monotonically_raises_posterior():
    low = update_posterior(EvidenceFactors(independent_units=1, prerequisites_satisfied=True))
    high = update_posterior(EvidenceFactors(independent_units=5, prerequisites_satisfied=True))
    assert high.posterior >= low.posterior


def test_more_assumptions_monotonically_lowers_posterior():
    few = update_posterior(EvidenceFactors(assumption_count=0, prerequisites_satisfied=True))
    many = update_posterior(EvidenceFactors(assumption_count=4, prerequisites_satisfied=True))
    assert many.posterior <= few.posterior


def test_unexecuted_prerequisite_lowers_posterior():
    ok = update_posterior(EvidenceFactors(prerequisites_satisfied=True))
    missing = update_posterior(EvidenceFactors(prerequisites_satisfied=False))
    assert missing.posterior < ok.posterior


def test_stable_retrieval_raises_vs_unstable():
    stable = update_posterior(EvidenceFactors(
        stability_measured=True, stability_stable=True, prerequisites_satisfied=True))
    unstable = update_posterior(EvidenceFactors(
        stability_measured=True, stability_stable=False, prerequisites_satisfied=False))
    assert stable.posterior > unstable.posterior


def test_abstention_lowers_posterior():
    answered = update_posterior(EvidenceFactors(prerequisites_satisfied=True))
    abstained = update_posterior(EvidenceFactors(prerequisites_satisfied=True, abstained=True))
    assert abstained.posterior < answered.posterior
