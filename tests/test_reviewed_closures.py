"""Closures a reviewer entered or confirmed (v0.7.0 closures; core.reviewed_closures), riders'
closure reports through the short Suggest form, and the alerts on saved routes
(core.saved_route_alerts)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from test_signed_out_suggestions import send
from test_stress_edits import LAT, LON, ME, WAY, addr, make_user, sign_in
from test_suggestions import live, router

from core import reviewed_closures, saved_route_alerts, stress_edits, suggestions, workzones
from core.models import AuditLogEntry, ReviewedClosure, SavedRoute, StressSuggestion
from routemaker import workzones as wz

FIXTURES = (live, router)
db = pytest.mark.django_db(transaction=True)

ENTER = "/api/closures/reviewed"
# A line along the road (way 5001 runs from LON to LON + 0.002 at LAT) and past both its ends.
ALONG = [[LON - 0.003 + i * 0.0005, LAT] for i in range(17)]
ELSEWHERE = [[LON - 0.003 + i * 0.0005, LAT + 0.01] for i in range(17)]


@pytest.fixture(autouse=True)
def _fresh_snapshot():
    workzones.forget()
    yield
    workzones.forget()


def days(n: int) -> str:
    from routemaker import ridetime

    return (timezone.now().astimezone(ridetime.ZONE).date() + timedelta(days=n)).isoformat()


def reviewer_client(user=None):
    client = Client(enforce_csrf_checks=True)
    sign_in(client, user or make_user())
    assert client.get(ME, **addr()).status_code == 200
    client.get("/api/me/routes", **addr())  # the security token, for anyone signed in
    return client, client.cookies["csrftoken"].value


def post(client, csrf, path, body):
    return client.post(
        path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **addr()
    )


def test_who_may_review() -> None:
    class Someone:
        is_authenticated = True
        is_active = True
        is_instance_admin = False
        _reviewer_guild_ids = frozenset()

    rider = Someone()
    assert not reviewed_closures.may_review(rider)
    rider._reviewer_guild_ids = frozenset({1234})
    assert reviewed_closures.may_review(rider)
    rider.is_banned = True
    assert not reviewed_closures.may_review(rider)
    admin = Someone()
    admin.is_instance_admin = True
    assert reviewed_closures.may_review(admin)
    assert not reviewed_closures.may_review(None)


def test_the_dates_are_the_regions_days_and_checked() -> None:
    start, end = reviewed_closures.window(days(1), days(3))
    assert (end - start) == timedelta(days=3)
    assert start.utcoffset() is not None
    with pytest.raises(stress_edits.Invalid) as error:
        reviewed_closures.window(days(3), days(1))
    assert error.value.field == "end"
    with pytest.raises(stress_edits.Invalid):
        reviewed_closures.window(days(-5), days(-2))  # over already
    with pytest.raises(stress_edits.Invalid):
        reviewed_closures.window("next week", None)
    assert reviewed_closures.window(None, None)[1] is None  # until a reviewer ends it


def test_a_source_link_must_be_a_web_address() -> None:
    assert reviewed_closures.clean_url(" https://example.org/notice ") == (
        "https://example.org/notice"
    )
    assert reviewed_closures.clean_url("") == ""
    for bad in ("javascript:alert(1)", "example.org", "ftp://example.org/x"):
        with pytest.raises(stress_edits.Invalid):
            reviewed_closures.clean_url(bad)


@db
class TestEntering:
    def test_a_reviewer_enters_a_closure_and_it_routes_and_checks_like_a_feeds(self, live) -> None:
        client, csrf = reviewer_client()
        answer = post(
            client,
            csrf,
            ENTER,
            {
                "osm_way_ids": [WAY],
                "reason": "Bridge deck replacement",
                "end": days(10),
                "url": "https://example.org/notice",
            },
        )
        assert answer.status_code == 201, answer.content
        assert answer.json()["message"].startswith("Closure confirmed: Oak Street, closed until ")
        row = ReviewedClosure.objects.get()
        assert row.osm_way_ids == [WAY] and row.road == "Oak Street"
        assert row.lines == [[[LON, LAT], [LON + 0.002, LAT]]]
        assert AuditLogEntry.objects.filter(action="closure_enter").count() == 1

        snap = workzones.snapshot()
        assert snap.status == {"reviewer": workzones.CURRENT}
        (zone,) = snap.zones
        assert (zone.source, zone.kind, zone.url) == (
            "reviewer",
            wz.CLOSED,
            "https://example.org/notice",
        )
        # The closure check names it, credited to the reviewer.
        found = workzones.closures_on(ALONG)
        (closure,) = found["closures"]
        assert closure["source_name"] == "Confirmed by a RouteMaker reviewer"
        assert closure["title"] == "Oak Street: closed"
        assert workzones.closures_on(ELSEWHERE)["closures"] == []
        # A plan through it routes round it, as a feed's closure.
        from routemaker import ridetime

        plan = workzones.plan_zones([ALONG[0], ALONG[-1]], ridetime.when_at(timezone.now()))
        assert [z.zone_id for z in plan.excluded] == [zone.zone_id]
        assert wz.heads_up(zone, 100).startswith("Road closed ahead at ")

        # Listed for the reviewer, and ended early.
        listed = client.get(ENTER, **addr()).json()
        assert [c["id"] for c in listed["closures"]] == [row.pk]
        ended = post(client, csrf, f"{ENTER}/{row.pk}/end", {})
        assert ended.status_code == 200 and "open again" in ended.json()["message"]
        assert workzones.snapshot().zones == ()
        assert post(client, csrf, f"{ENTER}/{row.pk}/end", {}).status_code == 409

    def test_the_named_stretch_is_asked_of_the_reviewers_own_endpoint(self, live) -> None:
        client, _csrf = reviewer_client()
        answer = client.get(f"/api/closures/stretch/{WAY}", **addr())
        # Oak Street meets only other names at its ends: the piece is the whole stretch.
        assert answer.status_code == 200 and answer.json() == {"stretch": None}
        rider, _ = reviewer_client(make_user(admin=False))
        assert rider.get(f"/api/closures/stretch/{WAY}", **addr()).status_code == 403

    def test_a_rider_who_is_not_a_reviewer_cannot(self, live) -> None:
        client, csrf = reviewer_client(make_user(admin=False))
        answer = post(client, csrf, ENTER, {"osm_way_ids": [WAY], "reason": "Closed"})
        assert answer.status_code == 403
        assert client.get(ENTER, **addr()).status_code == 403
        assert ReviewedClosure.objects.count() == 0
        anonymous = Client()
        assert anonymous.get(ENTER, **addr()).status_code == 401

    def test_what_is_refused(self, live) -> None:
        client, csrf = reviewer_client()
        assert post(client, csrf, ENTER, {"osm_way_ids": [WAY], "reason": " "}).json()["field"] == (
            "reason"
        )
        assert post(client, csrf, ENTER, {"osm_way_ids": [99], "reason": "x"}).status_code == 404
        both = {"osm_way_ids": [WAY], "line": ALONG[:3], "reason": "x"}
        assert post(client, csrf, ENTER, both).status_code == 400
        # Without the security token.
        bare = client.post(
            ENTER, json.dumps({"osm_way_ids": [WAY], "reason": "x"}),
            content_type="application/json", **addr(),
        )  # fmt: skip
        assert bare.status_code == 403
        assert ReviewedClosure.objects.count() == 0

    def test_a_drawn_line_is_a_closure_too(self, live) -> None:
        closure = reviewed_closures.create(make_user(), line=ALONG[4:9], reason="Fenced off")
        assert closure.osm_way_ids == [] and closure.lines == [ALONG[4:9]]
        assert [c["title"] for c in workzones.closures_on(ALONG)["closures"]] == ["Closed"]

    def test_one_with_no_end_holds_on_a_later_ride_until_a_reviewer_ends_it(self, live) -> None:
        reviewed_closures.create(make_user(), [WAY], "Bridge out")
        later = timezone.now() + timedelta(days=5)
        found = workzones.closures_on(ALONG, at=later)
        assert [c["may_still_apply"] for c in found["closures"]] == [False]

    def test_a_closure_that_starts_later_is_not_in_force_now(self, live) -> None:
        reviewed_closures.create(make_user(), [WAY], "Race", start=days(2), end=days(2))
        assert workzones.closures_on(ALONG)["closures"] == []
        assert len(workzones.snapshot().zones) == 1


@db
class TestRiderReports:
    def test_a_closed_report_needs_no_level_and_waits_with_the_closures(self, live) -> None:
        report = send(step=3, reasons=("closed",))  # the road's own level: no change asked
        assert report.kind == StressSuggestion.Kind.CLOSURE
        assert report.reason == "Closed (works, an event, fenced off)"
        # Not in the levels' review, and not approved as a level.
        assert suggestions.open_suggestions() == []
        with pytest.raises(suggestions.Conflict):
            suggestions.approve(make_user(), report.pk)
        assert [r.pk for r in reviewed_closures.open_reports()] == [report.pk]

    def test_a_reviewer_confirms_or_rejects_a_report(self, live) -> None:
        client, csrf = reviewer_client()
        report = send(step=3, reasons=("closed",))
        listed = client.get(ENTER, **addr()).json()
        assert [r["id"] for r in listed["reports"]] == [report.pk]
        answer = post(client, csrf, f"/api/closures/reports/{report.pk}/confirm", {"end": days(1)})
        assert answer.status_code == 201, answer.content
        closure = ReviewedClosure.objects.get()
        assert closure.report_id == report.pk and closure.reason == report.reason
        report.refresh_from_db()
        assert report.status == StressSuggestion.Status.APPROVED
        again = post(client, csrf, f"/api/closures/reports/{report.pk}/confirm", {})
        assert again.status_code == 409

        other = send(address="203.0.113.5", step=3, reasons=("closed",))
        rejected = post(client, csrf, f"/api/closures/reports/{other.pk}/reject", {})
        assert rejected.status_code == 200
        other.refresh_from_db()
        assert other.status == StressSuggestion.Status.DELETED
        assert ReviewedClosure.objects.count() == 1

    def test_a_level_suggestion_is_not_a_closure_report(self, live) -> None:
        level = send(step=2, reasons=("calmer",))
        with pytest.raises(stress_edits.NotFound):
            reviewed_closures.confirm_report(make_user(), level.pk)


@db
class TestSavedRouteAlerts:
    def saved(self, user, line=ALONG) -> SavedRoute:
        return SavedRoute.objects.create(
            user=user, name="Commute", line=line, distance_m=1200.0, inputs={}
        )

    def test_a_closure_on_a_saved_route_is_said_in_my_routes_until_it_ends(self, live) -> None:
        rider = make_user(admin=False)
        mine, other = self.saved(rider), self.saved(rider, ELSEWHERE)
        closure = reviewed_closures.create(make_user(), [WAY], "Bridge works", end=days(10))
        said = saved_route_alerts.refresh_all()
        assert said.startswith("saved routes: 2 checked, 1 with a closure on them")
        mine.refresh_from_db()
        other.refresh_from_db()
        (alert,) = mine.closure_alerts
        assert alert["text"].startswith("Closed on your route: Oak Street, until ")
        assert alert["source"] == "Confirmed by a RouteMaker reviewer"
        assert other.closure_alerts == []

        client = Client()
        sign_in(client, rider)
        listed = client.get("/api/me/routes", **addr()).json()["routes"]
        alerts = {r["name"] + str(r["id"]): r["closure_alerts"] for r in listed}
        assert alerts[f"Commute{mine.pk}"] == [alert]

        reviewed_closures.end_now(make_user(), closure.pk)
        saved_route_alerts.refresh_all()
        mine.refresh_from_db()
        assert mine.closure_alerts == []

    def test_a_route_is_checked_when_it_is_saved(self, live) -> None:
        reviewed_closures.create(make_user(), [WAY], "Bridge works")
        rider = make_user(admin=False)
        client = Client(enforce_csrf_checks=True)
        sign_in(client, rider)
        client.get("/api/me/routes", **addr())
        answer = client.post(
            "/api/me/routes",
            json.dumps({"name": "Loop", "line": ALONG, "distance_m": 1200.0, "inputs": {}}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            **addr(),
        )
        assert answer.status_code == 201, answer.content
        (alert,) = answer.json()["closure_alerts"]
        assert alert["text"] == "Closed on your route: Oak Street, no end date given."
