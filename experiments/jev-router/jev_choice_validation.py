"""Fail-closed validation for the recovered JEV four-way choice response.

This checks internal consistency, not provider compatibility or calibration.
"""
import math

ROUTES = frozenset(["simple_task","complex_task","needs_review","other"])
TOLERANCE = 1e-6


def validate_choice(answer):
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("Invalid Jev response schema")
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice not in ROUTES:
        raise ValueError("Unrecognized Jev route")
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Invalid Jev confidence")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != ROUTES:
        raise ValueError("Invalid Jev probability keys")
    for value in probabilities.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Invalid Jev probability value")
    if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0, abs_tol=TOLERANCE):
        raise ValueError("Jev probabilities do not sum to one")
    top = max(probabilities.values())
    winners = [key for key, value in probabilities.items() if value == top]
    if len(winners) != 1 or winners[0] != choice:
        raise ValueError("Jev selected choice conflicts with probabilities")
    # Confidence semantics vary by model version; do not equate it to a probability.
    return choice, float(confidence)
