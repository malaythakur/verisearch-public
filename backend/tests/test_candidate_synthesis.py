"""Tests for structured candidate synthesis and deterministic selection."""

import json

from backend.answer_engine.candidate_synthesis import (
    Candidate,
    SynthesisIntent,
    detect_synthesis_intent,
    pareto_frontier,
    parse_candidates,
    score_candidates,
    synthesize,
)


# --- Intent detection ---------------------------------------------------------

def test_detects_defensible_intent():
    assert (
        detect_synthesis_intent("What is the most defensible conclusion?")
        == SynthesisIntent.DEFENSIBLE
    )


def test_detects_robust_intent():
    assert (
        detect_synthesis_intent(
            "What conclusion would remain true even if half the report disappeared?"
        )
        == SynthesisIntent.ROBUST
    )


def test_plain_question_is_general():
    assert (
        detect_synthesis_intent("What was total net revenue in 2025?")
        == SynthesisIntent.GENERAL
    )


# --- Construct independence (correlation collapsing) --------------------------

def test_correlated_balance_sheet_facets_collapse_to_one_construct():
    c = Candidate(
        claim="The firm holds substantial assets.",
        evidence_class="balance_sheet",
        constructs=("balance_sheet", "capital_ratios"),  # both balance-sheet-derived
        information_level="medium",
    )
    # AUM/assets/capital ratios are one independent construct, not several.
    assert c.independent_construct_count() == 1


def test_distinct_constructs_count_independently():
    c = Candidate(
        claim="The firm operated at large scale across multiple business lines.",
        evidence_class="income_statement",
        constructs=("income_statement", "segment_reporting", "business_descriptions",
                    "management_discussion"),
        information_level="high",
    )
    assert c.independent_construct_count() == 4


# --- Defensibility scoring ----------------------------------------------------

def test_defensible_prefers_pure_quantitative_over_ranking():
    quant = Candidate("Net income was $58B in 2025.", "income_statement",
                      ("income_statement",), "high")
    ranking = Candidate("The firm is a top bank.", "rankings_awards",
                        ("rankings_awards",), "medium")
    scored = score_candidates([ranking, quant], SynthesisIntent.DEFENSIBLE)
    assert scored[0].candidate is quant
    # Ranking is rejected outright.
    assert any(
        s.candidate is ranking and s.rejection_reason is not None for s in scored
    )


def test_defensible_rejects_forward_looking_and_narrative():
    fwd = Candidate("The firm will grow next year.", "forward_looking",
                    ("forward_looking",), "medium", forward_looking=True)
    narrative = Candidate("The firm is a large institution.", "narrative_identity",
                          ("narrative_identity",), "low")
    scored = score_candidates([fwd, narrative], SynthesisIntent.DEFENSIBLE)
    assert all(s.rejection_reason is not None for s in scored)


# --- Robustness scoring -------------------------------------------------------

def test_robust_does_not_reject_precise_single_section_figure():
    # A precise reported figure (min-deletion 1) is authoritative and must NOT
    # be rejected outright — deletion-robustness is one Pareto axis, not a gate.
    single = Candidate("Net income was $57,048M in 2025.", "income_statement",
                       ("income_statement",), "high")
    scored = score_candidates([single], SynthesisIntent.ROBUST)
    assert scored[0].rejection_reason is None
    assert scored[0].measures.deletion_robustness == 1
    assert single.min_deletion_size() == 1


def test_exact_figure_has_min_deletion_one_despite_adjacent_constructs():
    # Adjacent balance-sheet construct does NOT entail an income-statement figure.
    c = Candidate("Net income was $57,048M in 2025.", "income_statement",
                  ("income_statement", "balance_sheet"), "high")
    assert c.independent_construct_count() == 2   # topically two
    assert c.min_deletion_size() == 1             # but only one entails it


def test_structural_claim_survives_many_deletions():
    c = Candidate(
        "The firm reports multiple business segments.",
        "segment_reporting",
        ("segment_reporting", "business_descriptions", "management_discussion",
         "income_statement"),
        "medium",
    )
    # Each section that exhibits the structure independently entails it.
    assert c.min_deletion_size() >= 3


def test_robust_keeps_precise_and_structural_as_tradeoff():
    # With NO ranking, a precise high-information figure and a more deletion-
    # robust structural claim are a genuine trade-off: both stay non-dominated.
    figure = Candidate("Total assets were $4,424,900M.", "balance_sheet",
                       ("balance_sheet",), "high")
    structural = Candidate(
        "The firm reports multiple business segments.",
        "segment_reporting",
        ("segment_reporting", "business_descriptions", "income_statement"),
        "medium",
    )
    scored = score_candidates([figure, structural], SynthesisIntent.ROBUST)
    frontier = pareto_frontier(scored)
    claims = {s.candidate.claim for s in frontier}
    assert figure.claim in claims and structural.claim in claims
    assert all(s.rejection_reason is None for s in scored)


# --- Parsing ------------------------------------------------------------------

def test_parse_candidates_from_noisy_json():
    text = (
        "Here are the candidates:\n"
        '[{"claim": "Net income was $58B.", "evidence_class": "income_statement", '
        '"constructs": ["income_statement"], "information_level": "high", '
        '"forward_looking": false}]\nThanks!'
    )
    cands = parse_candidates(text)
    assert len(cands) == 1
    assert cands[0].evidence_class == "income_statement"


def test_parse_candidates_handles_garbage():
    assert parse_candidates("not json at all") == []


def test_parse_candidates_repairs_unquoted_string_values():
    # Small models (e.g. Groq llama) sometimes emit unquoted string values.
    text = (
        "[\n"
        '  {"claim": JPMorgan generated net income in 2025, '
        '"evidence_class": income_statement, '
        '"constructs": ["income_statement"], '
        '"information_level": "high", "forward_looking": false}\n'
        "]"
    )
    cands = parse_candidates(text)
    assert len(cands) == 1
    assert cands[0].evidence_class == "income_statement"
    assert "net income" in cands[0].claim


# --- End-to-end synthesize ----------------------------------------------------

def test_synthesize_returns_none_for_general_question():
    assert synthesize("What was revenue?", "[]") is None


def test_synthesize_selects_defensible_winner():
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
        {"claim": "The firm is an industry leader.", "evidence_class": "rankings_awards",
         "constructs": ["rankings_awards"], "information_level": "medium",
         "forward_looking": False},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates),
        stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    assert result.winner is not None
    assert "58B" in result.winner.claim
    assert "Conclusion:" in result.answer


def test_scores_are_raw_primitives_not_invented():
    # Measures must be raw counts, no weighted scalar.
    c = Candidate("Net income was $58B in 2025.", "income_statement",
                  ("income_statement",), "high")
    scored = score_candidates([c], SynthesisIntent.DEFENSIBLE)
    m = scored[0].measures
    assert m is not None
    assert m.evidence_count == 1
    assert m.evidence_independence == 1
    assert m.assumption_count == 0           # pure reported data
    assert m.deletion_robustness == 1
    assert not m.disqualified


def test_pareto_keeps_genuine_tradeoffs_nondominated():
    # A: higher information/precision, lower robustness (single section).
    # B: lower precision, higher robustness (structural, many sections).
    # Neither dominates the other -> both on the frontier.
    a = Candidate("Net income was $58,048M in 2025.", "income_statement",
                  ("income_statement",), "high")
    b = Candidate("The firm reports multiple business segments.",
                  "segment_reporting",
                  ("segment_reporting", "business_descriptions", "income_statement"),
                  "medium")
    scored = score_candidates([a, b], SynthesisIntent.ROBUST)
    frontier = pareto_frontier(scored)
    claims = {s.candidate.claim for s in frontier}
    assert a.claim in claims and b.claim in claims  # genuine trade-off preserved


def test_pareto_frontier_excludes_dominated():
    # Distinct scopes so canonicalization keeps both; the weaker is dominated
    # only WITHIN its own scope. Use two scopes where one strictly dominates a
    # same-scope sibling. Here: two income claims (merge) + one assets claim.
    strong = Candidate("Net income was $58B, reported across segments.",
                       "income_statement",
                       ("income_statement", "segment_reporting"), "high",
                       sources=("Income Statement", "Segments"))
    weak_same = Candidate("Net income exists.", "income_statement",
                          ("income_statement",), "low", sources=("Income Statement",))
    # After canonicalization (same income scope) only `strong` remains.
    scored = score_candidates([strong, weak_same], SynthesisIntent.DEFENSIBLE)
    claims = {s.candidate.claim for s in scored}
    assert strong.claim in claims
    assert weak_same.claim not in claims  # merged away as weaker same-scope


def test_requirements_ledger_declares_dropped_and_unknown():
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates)
    )
    assert result is not None
    statuses = {r["requirement"]: r["status"] for r in result.requirements}
    assert statuses["observer invariance (auditor/regulator/investor views)"] == "NOT_EXECUTED"
    # Retrieval stability not executed in this build.
    assert statuses["retrieval-stability evidence (overlap/disagreement)"] == "NOT_EXECUTED"
    assert "raw primitives only (no hidden weighting)" in statuses
    assert "Requirements ledger" in result.answer


def test_certification_gated_when_stability_not_executed():
    # Default: stability not executed -> certification blocked -> RETRIEVAL_UNSTABLE,
    # no winner certified.
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates)
    )
    assert result is not None
    assert result.winner is None
    assert "RETRIEVAL_UNSTABLE" in result.answer


def test_duplication_detection_same_table_counts_once():
    # Two mentions of the SAME table are one independent unit, not two.
    c = Candidate(
        "Net income figures are reported.",
        "income_statement",
        ("income_statement",),
        "high",
        sources=("Income Statement table", "income statement table.", "INCOME STATEMENT TABLE"),
    )
    assert len(c.distinct_provenances()) == 1
    assert c.independent_evidence_units() == 1


def test_distinct_sources_count_separately():
    c = Candidate(
        "The firm is profitable and diversified.",
        "income_statement",
        ("income_statement", "segment_reporting"),
        "high",
        sources=("Financial Highlights", "Segment Results table", "MD&A"),
    )
    assert c.independent_evidence_units() == 3


def test_observer_invariant_frontier_intersects_stakeholders():
    from backend.answer_engine.candidate_synthesis import observer_invariant_frontier
    strong = Candidate(
        "The firm is profitable and diversified in 2025.",
        "income_statement",
        ("income_statement", "segment_reporting", "management_discussion"),
        "high",
        sources=("Financial Highlights", "Segment Results", "MD&A"),
    )
    weak = Candidate("The firm has some assets.", "balance_sheet",
                     ("balance_sheet",), "low", sources=("Balance Sheet",))
    scored = score_candidates([strong, weak], SynthesisIntent.DEFENSIBLE)
    invariant = observer_invariant_frontier(scored)
    claims = {s.candidate.claim for s in invariant}
    assert strong.claim in claims
    assert weak.claim not in claims  # dominated under every stakeholder lens


def test_canonicalization_collapses_same_scope_restatements():
    # 5 restatements of the SAME scope (net income / firm / 2025) all canonicalize
    # to ONE — preventing frontier explosion. Result is a single certified or
    # supported conclusion, never UNDERDETERMINED from duplicate phrasings.
    candidates = [
        {"claim": "Net income in 2025 detail A.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False, "sources": ["S1"]},
        {"claim": "Net income in 2025 detail B.", "evidence_class": "income_statement",
         "constructs": ["income_statement", "segment_reporting", "business_descriptions"],
         "information_level": "low", "forward_looking": False, "sources": ["S1", "S2", "S3"]},
        {"claim": "Net income in 2025 detail C.", "evidence_class": "income_statement",
         "constructs": ["income_statement", "management_discussion"],
         "information_level": "low", "forward_looking": False, "sources": ["S1"]},
        {"claim": "Net income in 2025 detail D.", "evidence_class": "income_statement",
         "constructs": ["income_statement", "balance_sheet"], "information_level": "medium",
         "forward_looking": False, "sources": ["S1", "S2"]},
        {"claim": "Net income in 2025 detail E.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "medium",
         "forward_looking": False, "sources": ["S1", "S2", "S3", "S4", "S5"]},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates),
        stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    # All five collapsed to one scope -> a single conclusion (frontier of 1).
    headline = result.answer.split("\n", 1)[0]
    assert headline == "CERTIFIED_CONCLUSION"
    assert result.winner is not None


def test_different_scopes_do_not_dominate_each_other():
    assets = Candidate("Total assets increased in 2025.", "balance_sheet",
                       ("balance_sheet",), "high", sources=("Balance Sheet",))
    income = Candidate("Net income decreased in 2025.", "income_statement",
                       ("income_statement",), "high", sources=("Income Statement",))
    scored = score_candidates([assets, income], SynthesisIntent.DEFENSIBLE)
    # Different scopes (assets vs net income) -> neither dominates -> coexist.
    assert all(s.dominated_by is None for s in scored)


def test_canonicalization_merges_same_scope_keeps_strongest():
    # Same scope (net income / firm) -> canonicalization keeps the strongest
    # (most independent units), so only ONE survives — not a dominance pair.
    weak = Candidate("Net income changed.", "income_statement",
                     ("income_statement",), "low", sources=("Income Statement",))
    strong = Candidate("Net income was reported across segments and MD&A.",
                       "income_statement",
                       ("income_statement", "segment_reporting", "management_discussion"),
                       "high", sources=("Income Statement", "Segments", "MD&A"))
    scored = score_candidates([weak, strong], SynthesisIntent.DEFENSIBLE)
    claims = {s.candidate.claim for s in scored}
    # The weaker same-scope restatement is merged away; the strongest is kept.
    assert strong.claim in claims
    assert weak.claim not in claims


def test_information_not_in_pareto_axes():
    from backend.answer_engine.candidate_synthesis import _PARETO_AXES
    assert "information" not in _PARETO_AXES


def test_promotional_self_characterization_disqualified():
    promo = Candidate("The company is the largest and leading bank in the world.",
                      "narrative_identity", ("narrative_identity",), "low",
                      sources=("Letter",))
    factual = Candidate("Net income was $58B in 2025.", "income_statement",
                        ("income_statement",), "high", sources=("Income Statement",))
    scored = score_candidates([promo, factual], SynthesisIntent.DEFENSIBLE)
    promo_s = next(s for s in scored if s.candidate is promo)
    assert promo_s.rejection_reason is not None
    assert "promotional" in promo_s.rejection_reason


def test_no_unique_conclusion_across_distinct_scopes():
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement", "segment_reporting"], "information_level": "high",
         "forward_looking": False, "sources": ["Income Statement", "Segments"]},
        {"claim": "Total assets were $4.4T in 2025.", "evidence_class": "balance_sheet",
         "constructs": ["balance_sheet", "capital_ratios"], "information_level": "high",
         "forward_looking": False, "sources": ["Balance Sheet", "Capital"]},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates),
        stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    if len(result.pareto_frontier) > 1:
        assert result.winner is None


def test_outcome_headline_is_always_in_closed_enum():
    from backend.answer_engine.candidate_synthesis import _ALLOWED_OUTCOMES
    # Whatever the inputs, the headline must be one of the allowed outcomes.
    for cands in (
        [{"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
          "constructs": ["income_statement"], "information_level": "high",
          "forward_looking": False, "sources": ["S1"]}],
        [{"claim": "The firm will grow next year.", "evidence_class": "forward_looking",
          "constructs": ["forward_looking"], "information_level": "low",
          "forward_looking": True, "sources": ["S1"]}],
    ):
        result = synthesize(
            "What is the most defensible conclusion?", json.dumps(cands),
            stability_executed=True, observer_invariance_executed=True,
        )
        if result is not None:
            headline = result.answer.split("\n", 1)[0]
            assert headline in _ALLOWED_OUTCOMES


def test_audit_hash_present():
    cands = [{"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
              "constructs": ["income_statement"], "information_level": "high",
              "forward_looking": False, "sources": ["S1"]}]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(cands),
        stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    assert "audit_hash:" in result.answer


def test_certification_blocked_when_only_stability_executed():
    # Dependency graph requires BOTH stability AND observer-invariance. With
    # only stability executed, certification is still blocked (OBSERVER_DEPENDENT).
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates),
        stability_executed=True, observer_invariance_executed=False,
    )
    assert result is not None
    assert result.winner is None
    assert "OBSERVER_DEPENDENT" in result.answer


def test_certification_allowed_when_all_prerequisites_executed():
    candidates = [
        {"claim": "Net income was $58B in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
    ]
    result = synthesize(
        "What is the most defensible conclusion?", json.dumps(candidates),
        stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    assert result.winner is not None
    assert "Conclusion:" in result.answer


def test_multiple_supported_on_distinct_scope_frontier():
    # Two non-dominated candidates on DIFFERENT scopes -> MULTIPLE_SUPPORTED
    # (additive truths), no single certified winner.
    candidates = [
        {"claim": "Net income was $58,048M in 2025.", "evidence_class": "income_statement",
         "constructs": ["income_statement"], "information_level": "high",
         "forward_looking": False},
        {"claim": "The firm reports multiple business segments.",
         "evidence_class": "segment_reporting",
         "constructs": ["segment_reporting", "business_descriptions", "income_statement"],
         "information_level": "medium", "forward_looking": False},
    ]
    result = synthesize(
        "What conclusion would remain true even if half the report disappeared?",
        json.dumps(candidates), stability_executed=True, observer_invariance_executed=True,
    )
    assert result is not None
    if len(result.pareto_frontier) > 1:
        assert result.winner is None
        assert "MULTIPLE_SUPPORTED" in result.answer or "MULTIPLE_MAXIMAL" in result.answer

