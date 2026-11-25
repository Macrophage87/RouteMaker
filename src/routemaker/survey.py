"""Survey spots: stretches whose rating was a low-confidence call, for riders to check on the spot.

The owner, 2026-11-25: "a mechanism for someone to click on that map and then answer some survey
questions about it", for the stretches the re-rate was unsure of. A spot's answers are evidence the
next re-rate gives its rater, never a rating by themselves (guidelines, not rulings).

This module holds the fixed question set and picks a spot's questions from what the rater said was
missing and the road's bike facility tags. `scripts/make_survey_spots.py` writes the spot list
(`fixtures/survey/spots.json`) with it. Pure: no database, no network.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: A spot holds at most this many questions, plus "When were you last here?" (always asked).
MAX_QUESTIONS = 4


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    options: tuple[tuple[str, str], ...]


NOT_SURE = ("not_sure", "Not sure")

QUESTIONS: dict[str, Question] = {
    q.key: q
    for q in (
        Question(
            "bike_lane",
            "What is the bike lane like?",
            (
                ("protected", "Posts, curb or parked cars between me and traffic"),
                ("painted", "Painted only"),
                ("sharrows", "Bike symbols in the traffic lane only"),
                ("none", "No bike lane"),
                NOT_SURE,
            ),
        ),
        Question(
            "side_path",
            "Is the path beside the road usable on a bike?",
            (
                ("good", "Yes, wide and smooth"),
                ("poor", "Narrow, rough or broken up"),
                ("none", "There is no path"),
                NOT_SURE,
            ),
        ),
        Question(
            "lanes",
            "How many lanes do cars have going your way? Leave out turn lanes and parking.",
            (("1", "One"), ("2", "Two"), ("3", "Three or more"), NOT_SURE),
        ),
        Question(
            "traffic",
            "How busy was it?",
            (
                ("quiet", "Quiet: a car now and then"),
                ("steady", "Steady: cars most of the time"),
                ("heavy", "Heavy: a stream of cars"),
                NOT_SURE,
            ),
        ),
        Question(
            "speed_sign",
            "What does the speed limit sign say?",
            (
                ("20", "20 mph or less"),
                ("25", "25 mph"),
                ("30", "30 mph"),
                ("35", "35 mph"),
                ("40", "40 mph or more"),
                ("none", "I saw no sign"),
                NOT_SURE,
            ),
        ),
        Question(
            "shoulder",
            "Is there a shoulder you could ride in?",
            (
                ("wide", "Yes, 4 ft or wider"),
                ("narrow", "Narrow or broken up"),
                ("none", "No shoulder"),
                NOT_SURE,
            ),
        ),
        Question(
            "bikes_allowed",
            "Is there a sign saying no bikes?",
            (("no_bikes", "Yes, no bikes"), ("allowed", "No such sign"), NOT_SURE),
        ),
    )
}

#: Always asked, first: how fresh the answer is. "longer" answers are kept but marked weak.
WHEN = Question(
    "when",
    "When were you last here?",
    (
        ("today", "Today"),
        ("week", "This week"),
        ("month", "This month"),
        ("longer", "Longer ago"),
    ),
)

_ORDER = ("bike_lane", "side_path", "lanes", "traffic", "speed_sign", "shoulder", "bikes_allowed")


def pick_questions(missing: Iterable[str], facilities: Iterable[str], why: str = "") -> list[str]:
    """The question keys for one stretch, in a fixed order, at most `MAX_QUESTIONS`.

    `missing` is the rater's list of facts it lacked ("measured speed", "through lanes", ...),
    `facilities` the stretch's bike facility tags as the re-rate input gives them ("none",
    "lane (lane)", "protected (track)", "none (separate)", ...), `why` the rater's Why. Traffic is
    always asked: every low-confidence call turns on how busy the road really is.
    """
    m = " ".join(missing).lower()
    fac = " ".join(f or "" for f in facilities).lower()
    w = why.lower()
    want = {"traffic"}
    if any(k in fac for k in ("track", "protected", "(lane", "lane (", "shared_lane")) or (
        "bike lane" in w and "no bike lane" not in w
    ):
        want.add("bike_lane")
    if "separate" in fac or "path beside" in w or "separate path" in w:
        want.add("side_path")
    if "lane" in m or "turn lane" in w or "lanes unknown" in w or "lane count" in w:
        want.add("lanes")
    if "speed" in m or "speed unknown" in w or "no speed" in w or "speed not given" in w:
        want.add("speed_sign")
    if "shoulder" in m or "shoulder" in fac:
        want.add("shoulder")
    if "access" in m:
        want.add("bikes_allowed")
    return [k for k in _ORDER if k in want][:MAX_QUESTIONS]


def answer_problems(questions: Iterable[str], answers: dict[str, str]) -> list[str]:
    """What is wrong with a rider's answers to a spot's questions; empty when they can be kept.

    `when` must be answered; every other question may be left out, and nothing outside the spot's
    questions is accepted.
    """
    allowed = {WHEN.key: WHEN, **{k: QUESTIONS[k] for k in questions if k in QUESTIONS}}
    out: list[str] = []
    if WHEN.key not in answers:
        out.append("when: required")
    for key, value in answers.items():
        q = allowed.get(key)
        if q is None:
            out.append(f"{key}: not asked at this spot")
        elif value not in {v for v, _ in q.options}:
            out.append(f"{key}: not one of the choices")
    return out
