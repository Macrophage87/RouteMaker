"""Survey spots: question picking, answer checks (routemaker.survey) and the spot list."""

from __future__ import annotations

import json
from pathlib import Path

from routemaker.survey import MAX_QUESTIONS, QUESTIONS, answer_problems, pick_questions

SPOTS = Path(__file__).resolve().parents[1] / "fixtures" / "survey" / "spots.json"


def test_traffic_is_always_asked():
    assert pick_questions([], ["none"]) == ["traffic"]


def test_protected_track_asks_about_the_bike_lane():
    assert "bike_lane" in pick_questions(["measured speed"], ["protected (track)"])


def test_no_bike_lane_in_the_why_does_not_ask_about_one():
    assert "bike_lane" not in pick_questions([], ["none"], "One lane, no bike lane, no count.")


def test_missing_facts_pick_their_questions_in_order():
    got = pick_questions(["speed", "through lanes", "shoulder width"], ["none"])
    assert got == ["lanes", "traffic", "speed_sign", "shoulder"]


def test_never_more_than_the_cap():
    got = pick_questions(
        ["speed", "lanes", "shoulder", "bike access"], ["lane (lane)", "none (separate)"]
    )
    assert len(got) == MAX_QUESTIONS


def test_when_is_required():
    assert answer_problems(["traffic"], {"traffic": "quiet"}) == ["when: required"]


def test_good_answers_pass_and_questions_may_be_skipped():
    assert answer_problems(["traffic", "lanes"], {"when": "today", "traffic": "heavy"}) == []


def test_unasked_question_and_unknown_choice_are_refused():
    got = answer_problems(["traffic"], {"when": "today", "lanes": "2", "traffic": "jammed"})
    assert got == ["lanes: not asked at this spot", "traffic: not one of the choices"]


def test_every_question_offers_not_sure():
    for q in QUESTIONS.values():
        assert "not_sure" in {v for v, _ in q.options}, q.key


def test_spot_list_is_well_formed():
    doc = json.loads(SPOTS.read_text())
    spots = doc["spots"]
    assert spots
    ids = [s["id"] for s in spots]
    assert len(ids) == len(set(ids))
    for s in spots:
        assert s["state"] in {"DC", "MD", "VA", "WV"}
        assert s["range"][0] <= 3 and s["range"][1] - s["range"][0] >= 1
        assert s["point_way"] in s["ways"]
        assert "traffic" in s["questions"] and len(s["questions"]) <= MAX_QUESTIONS
        assert set(s["questions"]) <= set(QUESTIONS)
