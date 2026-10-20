"""Tests for deterministic evidence-contract enforcement."""

from backend.answer_engine.evidence_contract import (
    enforce_evidence_contract,
    required_evidence_types,
)

_CONTRACT_Q = (
    "Build the strongest counterargument that 2025 performance was NOT "
    "stronger than 2024. Support it with BOTH a quantitative figure AND "
    "management commentary."
)


def test_required_types_parsed_from_contract_question():
    assert required_evidence_types(_CONTRACT_Q) == {
        "management_commentary",
        "quantitative",
    }


def test_non_contract_question_has_no_requirements():
    assert required_evidence_types("What was total net revenue in 2025?") == set()


def test_overrides_when_commentary_admitted_missing():
    answer = (
        "Nonaccrual loans rose from $2,984M to $3,632M [1]. Although there is "
        "no direct management commentary comparing 2025 to 2024, the "
        "counterargument is that 2025 was not stronger."
    )
    verdict = enforce_evidence_contract(_CONTRACT_Q, answer)
    assert verdict.enforced is True
    assert verdict.code == "NO_SUPPORTED_COUNTERARGUMENT"
    assert "management_commentary" in verdict.missing_types
    assert verdict.answer.startswith("NO_SUPPORTED_COUNTERARGUMENT")


def test_overrides_on_schema_leak_footnotes_as_commentary():
    answer = (
        "Revenue fell per the table [1]. The notes to the consolidated "
        "financial statements suggest management is monitoring credit quality, "
        "which indicates weaker performance."
    )
    verdict = enforce_evidence_contract(_CONTRACT_Q, answer)
    assert verdict.enforced is True
    assert verdict.code == "NO_SUPPORTED_COUNTERARGUMENT"


def test_does_not_override_non_contract_question():
    verdict = enforce_evidence_contract(
        "What was total net revenue in 2025?",
        "Total net revenue was $182,447M [1].",
    )
    assert verdict.enforced is False
    assert verdict.answer == "Total net revenue was $182,447M [1]."


def test_does_not_override_when_no_admission_of_missing_evidence():
    # Contract question, but the answer does not admit any required type is
    # missing -> the gate stays out of the way (it is conservative).
    answer = (
        "Per the MD&A, management noted softer markets revenue [1], and net "
        "income fell from $X to $Y [1], supporting that 2025 was not stronger."
    )
    verdict = enforce_evidence_contract(_CONTRACT_Q, answer)
    assert verdict.enforced is False
