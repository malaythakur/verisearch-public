"""Tests for the pairwise contradiction matrix (falsifier)."""

from backend.answer_engine.contradiction import (
    contradiction_matrix,
    detect_contradiction,
)


def test_directional_contradiction():
    a = "Net income increased in 2025."
    b = "Net income decreased in 2025."
    hit = detect_contradiction(a, b)
    assert hit is not None
    assert hit.type == "directional"
    assert hit.metric == "net income"


def test_negation_contradiction():
    a = "The firm reported net income growth."
    b = "The firm did not report net income growth."
    hit = detect_contradiction(a, b)
    assert hit is not None
    assert hit.type == "negation"


def test_numeric_contradiction():
    a = "Net income was $57,048 million."
    b = "Net income was $49,000 million."
    hit = detect_contradiction(a, b)
    assert hit is not None
    assert hit.type == "numeric"
    assert hit.artifact["a_value"] != hit.artifact["b_value"]


def test_different_metrics_are_not_contradictory():
    # The key fix: assets up and net income down are DIFFERENT metrics moving
    # differently — NOT a contradiction.
    a = "Total assets increased in 2025."
    b = "Net income decreased in 2025."
    assert detect_contradiction(a, b) is None


def test_no_contradiction_different_subjects():
    a = "Net income increased in 2025."
    b = "Employee headcount across offices."
    assert detect_contradiction(a, b) is None


def test_no_contradiction_same_direction():
    a = "Net income increased in 2025."
    b = "Net income grew strongly in 2025."
    assert detect_contradiction(a, b) is None


def test_matrix_finds_all_pairs():
    claims = [
        "Net income increased in 2025.",
        "Net income decreased in 2025.",
        "Total assets grew in 2025.",
    ]
    matrix = contradiction_matrix(claims)
    # Only the net-income up/down pair contradicts (assets is a different metric).
    assert len(matrix) == 1
    assert matrix[0].i == 0 and matrix[0].j == 1
    assert matrix[0].metric == "net income"
