"""Tests for the request-executability audit."""

from backend.answer_engine.request_executability import (
    TaskStatus,
    assess_executability,
)


# --- TASK_INCOMPLETE ----------------------------------------------------------

def test_optimize_meta_object_with_no_question_is_task_incomplete():
    v = assess_executability("Minimize regret.")
    assert not v.executable
    assert v.status == TaskStatus.TASK_INCOMPLETE
    assert v.code == "TASK_INCOMPLETE"
    assert v.next_action is not None
    assert any("underlying question" in m for m in v.missing)


def test_maximize_information_value_alone_is_task_incomplete():
    v = assess_executability("Maximize information value.")
    assert not v.executable
    assert v.status == TaskStatus.TASK_INCOMPLETE


def test_optimize_with_concrete_target_is_executable():
    # "minimize" + a concrete document target => there IS an objective.
    v = assess_executability("Minimize the error in the reported revenue figure.")
    assert v.executable


# --- CONTRADICTORY ------------------------------------------------------------

def test_brevity_and_verbosity_is_contradictory():
    v = assess_executability("In one word, explain in great detail why revenue grew.")
    assert not v.executable
    assert v.status == TaskStatus.CONTRADICTORY


def test_conflicting_exact_counts_is_contradictory():
    v = assess_executability("List exactly 5 and exactly 10 risk factors.")
    assert not v.executable
    assert v.status == TaskStatus.CONTRADICTORY


# --- UNDERDETERMINED ----------------------------------------------------------

def test_dangling_referent_is_underdetermined():
    v = assess_executability("Compare them.")
    assert not v.executable
    assert v.status == TaskStatus.UNDERDETERMINED


def test_which_is_better_alone_is_underdetermined():
    v = assess_executability("Which is better?")
    assert not v.executable
    assert v.status == TaskStatus.UNDERDETERMINED


# --- EXECUTABLE (no false positives) ------------------------------------------

def test_normal_question_is_executable():
    v = assess_executability("What was total net revenue in 2025?")
    assert v.executable
    assert v.status == TaskStatus.EXECUTABLE


def test_synthesis_question_is_executable():
    v = assess_executability("What is the most defensible conclusion from this report?")
    assert v.executable


def test_comparison_with_named_items_is_executable():
    v = assess_executability(
        "Compare the revenue of the Consumer and Commercial segments."
    )
    assert v.executable


def test_brevity_only_is_executable():
    v = assess_executability("Briefly, what was net income in 2025?")
    assert v.executable
