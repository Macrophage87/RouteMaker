"""Survey spots over the api (core.survey_spots): the layer, the questions, answers and the count.

Against a real live segment table (the `segment_schemas` fixture), with a two-spot list in place
of the committed file.
"""

from __future__ import annotations

import pytest
from test_accounts import addr, send, signed_in
from test_segment_info_api import insert

from core import survey_spots
from core.models import SurveyAnswer, SurveyDone

db = pytest.mark.django_db

A = survey_spots.Spot(
    "s101",
    "Ohio Drive Southwest",
    "DC",
    "District of Columbia",
    ("traffic", "speed_sign"),
    101,
    (1.5, 2.5),
)
B = survey_spots.Spot(
    "s202",
    "4th Street Northeast",
    "DC",
    "District of Columbia",
    ("bike_lane", "traffic"),
    202,
    (2.0, 3.5),
)
BOX = {"west": -77.1, "south": 38.8, "east": -76.9, "north": 39.0}


@pytest.fixture
def spots(segment_schemas, monkeypatch):
    live, _ = segment_schemas
    insert(live, 101, [(-77.04, 38.87), (-77.02, 38.87)])
    insert(live, 202, [(-77.00, 38.92), (-77.00, 38.94)])
    monkeypatch.setattr(survey_spots, "spots", lambda: {A.id: A, B.id: B})
    survey_spots._points.clear()
    yield
    survey_spots._points.clear()


def answer(client, csrf, spot="s101", **answers):
    return send(client, "post", "/api/survey/answer", {"spot": spot, "answers": answers}, csrf)


@db
class TestLayer:
    def test_spots_in_view_at_the_middle_of_their_way(self, client, spots) -> None:
        got = client.get("/api/survey/spots", BOX, **addr()).json()["spots"]
        assert [s["id"] for s in got] == ["s101", "s202"]
        assert got[0]["lon"] == pytest.approx(-77.03) and got[0]["lat"] == pytest.approx(38.87)
        assert got[0]["road"] == "Ohio Drive Southwest"

    def test_a_spot_outside_the_view_is_left_out(self, client, spots) -> None:
        box = {**BOX, "north": 38.9}
        got = client.get("/api/survey/spots", box, **addr()).json()["spots"]
        assert [s["id"] for s in got] == ["s101"]

    def test_near_is_nearest_first(self, client, spots) -> None:
        got = client.get(
            "/api/survey/near", {"lat": 38.93, "lon": -77.0, "miles": 10}, **addr()
        ).json()
        assert [s["id"] for s in got["spots"]] == ["s202", "s101"]
        assert got["spots"][0]["away_mi"] < 0.1

    def test_questions_start_with_when(self, client, spots) -> None:
        got = client.get("/api/survey/spots/s202/questions", **addr()).json()["questions"]
        assert [q["key"] for q in got] == ["when", "bike_lane", "traffic"]
        assert client.get("/api/survey/spots/nope/questions", **addr()).status_code == 404


@db
class TestAnswers:
    def test_signed_out_cannot_answer(self, client, spots) -> None:
        r = client.post("/api/survey/answer", {}, content_type="application/json", **addr())
        assert r.status_code in (401, 403)
        assert not SurveyAnswer.objects.exists()

    def test_an_answer_is_kept_without_the_account_and_hides_the_spot(self, spots) -> None:
        client, user, csrf = signed_in()
        r = answer(client, csrf, when="today", traffic="steady")
        assert r.status_code == 200 and r.json() == {"done": ["s101"], "count": 1}
        row = SurveyAnswer.objects.get()
        assert row.answers == {"when": "today", "traffic": "steady"}
        assert not hasattr(row, "user_id"), "an answer keeps no account"
        got = client.get("/api/survey/spots", BOX, **addr()).json()["spots"]
        assert [s["id"] for s in got] == ["s202"], "answered spots no longer show for them"
        other, _u, _c = signed_in()
        got = other.get("/api/survey/spots", BOX, **addr()).json()["spots"]
        assert len(got) == 2, "but still show for everyone else"

    def test_only_today_counts(self, spots) -> None:
        client, user, csrf = signed_in()
        answer(client, csrf, when="month", traffic="quiet")
        r = answer(client, csrf, spot="s202", when="today", bike_lane="painted")
        assert r.json() == {"done": ["s101", "s202"], "count": 1}
        assert client.get("/api/me/survey", **addr()).json()["count"] == 1

    def test_a_spot_is_answered_once(self, spots) -> None:
        client, user, csrf = signed_in()
        answer(client, csrf, when="today", traffic="quiet")
        r = answer(client, csrf, when="today", traffic="heavy")
        assert r.status_code == 409
        assert SurveyAnswer.objects.count() == 1 and SurveyDone.objects.count() == 1

    @pytest.mark.parametrize(
        "answers",
        [{"traffic": "quiet"}, {"when": "today", "lanes": "2"}, {"when": "today", "traffic": "x"}],
    )
    def test_bad_answers_are_refused(self, spots, answers) -> None:
        client, user, csrf = signed_in()
        r = send(client, "post", "/api/survey/answer", {"spot": "s101", "answers": answers}, csrf)
        assert r.status_code == 400
        assert not SurveyAnswer.objects.exists() and not SurveyDone.objects.exists()

    def test_an_unknown_spot_is_refused(self, spots) -> None:
        client, user, csrf = signed_in()
        assert answer(client, csrf, spot="s999", when="today").status_code == 400

    def test_a_write_needs_the_csrf_token(self, spots) -> None:
        client, user, _csrf = signed_in()
        assert answer(client, None, when="today").status_code == 403

    def test_the_done_list_goes_with_the_account(self, spots) -> None:
        client, user, csrf = signed_in()
        answer(client, csrf, when="today")
        user.delete()
        assert not SurveyDone.objects.exists()
        assert SurveyAnswer.objects.count() == 1, "the answer itself stays: it names no one"
