"""The review tool's spread reads the formula's half step (`stress_review.rating_sources`)."""

from __future__ import annotations

from core import stress_review


def test_the_review_spread_shows_the_formula_at_its_half_step() -> None:
    # A busy street the formula reads 2.5, with DDOT's 4 deciding the tier.
    row = {
        "step": 4.0,
        "ratings": {
            "formula": 2,
            "formula_half": True,
            "agencies": [{"agency": "ddot", "level": 4}],
        },
    }
    formula = next(s for s in stress_review.rating_sources(row) if s["key"] == "formula")
    assert formula["level"] == 2.5


def test_a_whole_formula_level_stays_whole_in_the_review_spread() -> None:
    row = {"step": 3.0, "ratings": {"formula": 3, "agencies": []}}
    formula = next(s for s in stress_review.rating_sources(row) if s["key"] == "formula")
    assert formula["level"] == 3.0
