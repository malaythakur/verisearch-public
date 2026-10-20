"""Operational, observable definition of a claim's information content.

The earlier `information` axis used the LLM's self-reported "high/medium/low",
which is not directly observable and can smuggle in hidden preference. This
module derives an information ordinal from OBSERVABLE features of the claim text
only, so the axis is a measured property, not an opinion:

  specificity_score = (#distinct numerals) + (#units/percent) + (#named entities)
                      + (#comparative/temporal qualifiers)

The continuous score is bucketed to an ordinal {0,1,2} so it composes with the
other raw Pareto primitives. Two analysts computing it from the same text get
the same number — that is the test for "observable".
"""

from __future__ import annotations

import re

_NUMERAL_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_UNIT_RE = re.compile(r"%|\$|€|£|\b(?:million|billion|bn|m|bps|percent|pp)\b", re.IGNORECASE)
# Proper nouns / named entities: capitalized tokens not at sentence start are a
# cheap observable proxy (e.g. "Commercial & Investment Bank", "CET1").
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+)*\b")
_QUALIFIER_RE = re.compile(
    r"\b(?:year[- ]over[- ]year|yoy|compared|increase|decrease|from\s+\d|"
    r"to\s+\d|since|during|in\s+20\d\d|over\s+the\s+past)\b",
    re.IGNORECASE,
)


def specificity_features(claim: str) -> dict:
    """Return the observable specificity features of a claim (auditable)."""
    text = claim or ""
    numerals = len(set(_NUMERAL_RE.findall(text)))
    units = len(_UNIT_RE.findall(text))
    # Exclude the leading word from entity counting (sentence-start capital).
    body = text.split(" ", 1)[1] if " " in text else ""
    entities = len(set(_ENTITY_RE.findall(body)))
    qualifiers = len(_QUALIFIER_RE.findall(text))
    return {
        "numerals": numerals,
        "units": units,
        "named_entities": entities,
        "qualifiers": qualifiers,
    }


def specificity_score(claim: str) -> int:
    f = specificity_features(claim)
    return f["numerals"] + f["units"] + f["named_entities"] + f["qualifiers"]


def information_ordinal(claim: str) -> int:
    """Bucket the observable specificity score to an ordinal {0,1,2}.

    0 = generic/low (no numerals, units, or entities),
    1 = some specificity,
    2 = highly specific (multiple observable specifics).

    Formula (fully reconstructable from observable counts):
        score = numerals + units + named_entities + qualifiers
        ordinal = 2 if score >= 4 else 1 if score >= 1 else 0
    """
    score = specificity_score(claim)
    if score >= 4:
        return 2
    if score >= 1:
        return 1
    return 0


# Documented, reconstructable derivation of the information ordinal.
INFORMATION_FORMULA = (
    "information = bucket(numerals + units + named_entities + qualifiers): "
    ">=4 -> 2, >=1 -> 1, else 0"
)


def information_breakdown(claim: str) -> dict:
    """Return the observable feature counts AND the derived ordinal.

    Makes `information` a fully measurable primitive: the ordinal is
    reconstructable from the integer feature counts via INFORMATION_FORMULA, so
    it carries no hidden preference.
    """
    f = specificity_features(claim)
    return {
        **f,
        "specificity_score": specificity_score(claim),
        "information_ordinal": information_ordinal(claim),
        "formula": INFORMATION_FORMULA,
    }
