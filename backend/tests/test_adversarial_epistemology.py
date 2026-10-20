"""Tests for adversarial epistemology — impossible-question detection."""

import json

from backend.answer_engine.adversarial_epistemology import (
    EpistemicCategory,
    Presupposition,
    Severity,
    classify_form,
    parse_presuppositions,
    verdict_from_presuppositions,
)


# --- Layer 1: form-detectable impossibility -----------------------------------

def test_detects_future_prediction():
    v = classify_form("What will net income be in 2027?")
    assert v is not None
    assert v.category == EpistemicCategory.FUTURE_PREDICTION
    assert not v.answerable


def test_detects_counterfactual():
    v = classify_form(
        "What would profit have been if they hadn't operated the investment bank?"
    )
    assert v is not None
    assert v.category == EpistemicCategory.COUNTERFACTUAL


def test_detects_private_intent():
    v = classify_form("What does the CEO secretly believe about the merger?")
    assert v is not None
    assert v.category == EpistemicCategory.PRIVATE_INTENT


def test_detects_out_of_corpus_competitor_comparison():
    v = classify_form("How does the firm's revenue compare to its competitors?")
    assert v is not None
    assert v.category == EpistemicCategory.OUT_OF_CORPUS


def test_normal_question_is_not_form_impossible():
    assert classify_form("What was total net revenue in 2025?") is None


def test_diversity_claim_is_not_counterfactual():
    # "if" guard should not over-trigger on ordinary questions.
    assert classify_form("Which segment had the highest revenue?") is None


# --- Layer 2: premise verification --------------------------------------------

def test_contradicted_core_premise_is_false_premise():
    presups = [
        Presupposition("Revenue declined in 2025.", is_core=True,
                       status="CONTRADICTED"),
    ]
    v = verdict_from_presuppositions("Why did revenue decline in 2025?", presups)
    assert not v.answerable
    assert v.category == EpistemicCategory.FALSE_PREMISE
    assert v.code == "FALSE_PREMISE_DETECTED"


def test_absent_core_premise_is_uncertainty_not_violation():
    # ABSENT core premise => unverifiable, but UNCERTAINTY (does not terminate).
    presups = [
        Presupposition("There was an accounting fraud.", is_core=True,
                       status="ABSENT"),
    ]
    v = verdict_from_presuppositions(
        "How much did the accounting fraud cost?", presups
    )
    assert not v.answerable
    assert v.category == EpistemicCategory.UNVERIFIABLE_PREMISE
    assert v.severity == Severity.UNCERTAINTY
    assert not v.terminates          # graded-execution: do NOT abort
    assert v.falsifier is not None   # operational: says what would unblock


def test_contradicted_core_premise_terminates():
    presups = [
        Presupposition("Revenue declined in 2025.", is_core=True,
                       status="CONTRADICTED"),
    ]
    v = verdict_from_presuppositions("Why did revenue decline in 2025?", presups)
    assert v.category == EpistemicCategory.FALSE_PREMISE
    assert v.severity == Severity.VIOLATION
    assert v.terminates              # a violation terminates


def test_supported_premises_are_answerable():
    presups = [
        Presupposition("The firm has business segments.", is_core=True,
                       status="SUPPORTED"),
    ]
    v = verdict_from_presuppositions("Which segment grew fastest?", presups)
    assert v.answerable
    assert v.category == EpistemicCategory.ANSWERABLE


def test_absent_noncore_premise_does_not_block():
    # A non-core absent presupposition should not make the question impossible.
    presups = [
        Presupposition("The firm has segments.", is_core=True, status="SUPPORTED"),
        Presupposition("The report mentions the weather.", is_core=False,
                       status="ABSENT"),
    ]
    v = verdict_from_presuppositions("Which segment grew fastest?", presups)
    assert v.answerable


def test_meta_reliability_presupposition_does_not_block():
    # "the data is accurate and reliable" is a meta-assumption every question
    # makes; it must never, on its own, render a question impossible.
    presups = [
        Presupposition("The revenue data for each segment is accurate and reliable.",
                       is_core=True, status="ABSENT"),
    ]
    v = verdict_from_presuppositions(
        "Which business segment grew fastest by revenue?", presups
    )
    assert v.answerable


def test_meta_completeness_presupposition_filtered():
    presups = [
        Presupposition("The report is complete.", is_core=True, status="ABSENT"),
        Presupposition("The sources are reliable.", is_core=True, status="ABSENT"),
    ]
    v = verdict_from_presuppositions("What was net revenue?", presups)
    assert v.answerable


# --- Parsing ------------------------------------------------------------------

def test_parse_presuppositions_handles_unquoted_values():
    text = (
        '[{"presupposition": Revenue declined in 2025, "is_core": true, '
        '"status": "CONTRADICTED"}]'
    )
    presups = parse_presuppositions(text)
    assert len(presups) == 1
    assert presups[0].status == "CONTRADICTED"
    assert presups[0].is_core is True


def test_parse_presuppositions_handles_garbage():
    assert parse_presuppositions("no json here") == []


def test_as_answer_lists_contradicted_and_absent():
    presups = [
        Presupposition("Revenue declined.", is_core=True, status="CONTRADICTED"),
        Presupposition("There was a layoff.", is_core=False, status="ABSENT"),
    ]
    v = verdict_from_presuppositions("Why did revenue decline?", presups)
    answer = v.as_answer()
    assert "FALSE_PREMISE_DETECTED" in answer
    assert "Revenue declined." in answer
