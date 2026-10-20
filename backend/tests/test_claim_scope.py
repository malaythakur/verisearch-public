"""Tests for claim scope, evidence hierarchy, and semantic guards."""

from backend.answer_engine.claim_scope import (
    EvidenceTier,
    derive_scope,
    same_scope,
)
from backend.answer_engine.contradiction import detect_contradiction
from backend.answer_engine.calibration import confidence_label


# --- Scope guard --------------------------------------------------------------

def test_same_metric_same_timeframe_is_same_scope():
    a = derive_scope("Net income rose in 2025.", "income_statement")
    b = derive_scope("Net income fell in 2025.", "income_statement")
    assert same_scope(a, b)  # comparable (and they directionally conflict)


def test_different_metric_is_different_scope():
    a = derive_scope("Total assets increased in 2025.", "balance_sheet")
    b = derive_scope("Net income decreased in 2025.", "income_statement")
    assert not same_scope(a, b)


def test_different_timeframe_is_different_scope():
    a = derive_scope("Net income rose in 2024.", "income_statement")
    b = derive_scope("Net income rose in 2025.", "income_statement")
    assert not same_scope(a, b)


def test_segment_subscope_separates_firm_from_segment():
    firm = derive_scope("Net income rose in 2025.", "income_statement")
    seg = derive_scope(
        "Commercial & Investment Bank net income rose in 2025.", "segment_reporting"
    )
    assert not same_scope(firm, seg)


# --- Evidence hierarchy -------------------------------------------------------

def test_primary_outranks_summary():
    primary = derive_scope("Net income was $58B in 2025.", "income_statement")
    summary = derive_scope("Net income looked healthy in 2025.", "management_discussion")
    assert primary.tier > summary.tier
    assert primary.tier == EvidenceTier.PRIMARY


def test_ratio_is_derived_tier():
    s = derive_scope("Return on equity was 17% in 2025.", "income_statement")
    assert s.tier == EvidenceTier.DERIVED


# --- Semantic contradiction guard --------------------------------------------

def test_requirement_does_not_contradict_observation():
    req = "The CET1 capital ratio must exceed 11%."
    obs = "The CET1 capital ratio was 14.6%."
    assert detect_contradiction(req, obs) is None


def test_observation_vs_observation_can_contradict():
    a = "Net income increased in 2025."
    b = "Net income decreased in 2025."
    assert detect_contradiction(a, b) is not None


# --- Calibration label --------------------------------------------------------

def test_calibration_label_unstable_when_prereq_missing():
    assert confidence_label(0.9, stability_stable=False, prerequisites_satisfied=False) == "UNSTABLE"


def test_calibration_label_bands():
    assert confidence_label(0.8, True, True) == "DIRECT"
    assert confidence_label(0.6, True, True) == "STRONG"
    assert confidence_label(0.4, True, True) == "WEAK"
