"""Signed-out LTS suggestions (v0.7.0; core.signed_out_suggestions): the short form's filters,
the per-device daily limits kept as a salted daily hash, and the review list's grouping."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.test import Client
from django.utils import timezone
from test_stress_edits import LAT, LON, WAY, make_user
from test_suggestions import live, router

from core import signed_out_suggestions as quick
from core import stress_edits, suggestions
from core.models import AuditLogEntry, SignedOutSend, StressSuggestion

# The road and its cross streets, and the router, by name (test_suggestions).
FIXTURES = (live, router)
db = pytest.mark.django_db(transaction=True)

TICKET = "/api/stress-suggestions/ticket"
SEND = "/api/stress-suggestions/signed-out"
ADDRESS = "203.0.113.77"
OTHER_ROAD = 6001  # Elm Street, LTS 2 (test_suggestions' cross street)


def send(address=ADDRESS, way=WAY, step=2, reasons=("calmer",), other="", honeypot="", ticket=None):
    return quick.create(
        address,
        way,
        LAT,
        {WAY: LON + 0.001, OTHER_ROAD: LON, 6002: LON + 0.002}[way],
        step,
        list(reasons),
        other,
        quick.ticket(way) if ticket is None else ticket,
        honeypot,
    )


def anonymous():
    client = Client(enforce_csrf_checks=True)
    headers = {"HTTP_X_FORWARDED_FOR": ADDRESS}
    answer = client.get(TICKET, {"way": WAY}, **headers)
    assert answer.status_code == 200, answer.content
    return client, answer.json(), client.cookies["csrftoken"].value, headers


def test_emails_and_phone_numbers_are_taken_out_of_other() -> None:
    assert quick.screen("mail me at a.b+c@example.org or 301-555-0123 please") == (
        "mail me at [removed] or [removed] please"
    )
    assert quick.screen("(202) 555 0199") == "[removed]"
    # Speeds, lanes and years stay.
    assert (
        quick.screen("cars at 45 mph, 2 lanes, since 2021") == "cars at 45 mph, 2 lanes, since 2021"
    )


def test_a_device_is_a_salted_hash_of_its_address_and_the_day() -> None:
    today = quick.device_hash(ADDRESS, date(2026, 10, 15))
    assert len(today) == 64 and ADDRESS not in today
    assert today == quick.device_hash(ADDRESS, date(2026, 10, 15))
    assert today != quick.device_hash(ADDRESS, date(2026, 10, 16))
    assert today != quick.device_hash("203.0.113.78", date(2026, 10, 15))


def test_a_ticket_is_for_its_road_only() -> None:
    assert quick.ticket_ok(quick.ticket(WAY), WAY)
    assert not quick.ticket_ok(quick.ticket(WAY), OTHER_ROAD)
    assert not quick.ticket_ok("forged", WAY) and not quick.ticket_ok(None, WAY)


@db
class TestShortForm:
    def test_anyone_signed_out_sends_and_it_waits_for_review_with_no_account_or_address(
        self, live
    ) -> None:
        client, ticket, csrf, headers = anonymous()
        assert ticket["reasons"][0] == ["fast_traffic", "Fast traffic"]
        assert ticket["reasons"][-1] == ["other", "Other"]
        body = {
            "osm_way_id": WAY,
            "lat": LAT,
            "lon": LON + 0.001,
            "step": 2.0,
            "reasons": ["calmer", "other"],
            "other": "Quiet all day; call 301-555-0123",
            "ticket": ticket["ticket"],
            "website": "",
        }
        answer = client.post(
            SEND,
            json.dumps(body),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            **headers,
        )
        assert answer.status_code == 200, answer.content
        assert answer.json()["message"].startswith("Thanks.")
        row = StressSuggestion.objects.get()
        assert row.signed_out and row.suggester is None and row.suggester_user_id is None
        assert row.reasons == ["calmer", "other"]
        assert row.reason == "Feels calmer than rated; Other: Quiet all day; call [removed]"
        assert (row.tier, row.half, row.current_tier, row.status) == (2, False, 3, "pending")
        # The address is nowhere: only its salted daily hash, for a day.
        stored = [s.device for s in SignedOutSend.objects.all()]
        assert len(stored) == 1 and ADDRESS not in stored[0]
        assert AuditLogEntry.objects.filter(action="stress_suggest_signed_out").count() == 1
        # Without the security token: refused.
        again = client.post(SEND, json.dumps(body), content_type="application/json", **headers)
        assert again.status_code == 403

    def test_the_filters_drop_what_says_nothing(self, live) -> None:
        def refused(**change):
            with pytest.raises(stress_edits.EditRefused) as error:
                send(**change)
            return error.value

        assert refused(step=3).field == "step"  # no change
        assert refused(reasons=()).field == "reasons"  # a slider move with no reason
        assert refused(reasons=("bogus",)).field == "reasons"
        assert refused(reasons=("other",)).field == "other"
        assert refused(reasons=("other",), other="x" * 201).field == "other"
        assert refused(ticket="").code == "no_ticket"  # never opened on this road
        assert refused(ticket=quick.ticket(OTHER_ROAD)).code == "no_ticket"
        with pytest.raises(quick.Dropped):
            send(honeypot="https://spam.example")
        assert StressSuggestion.objects.count() == 0 and SignedOutSend.objects.count() == 0

    def test_one_a_road_and_ten_a_day_per_device(self, live, monkeypatch) -> None:
        send()
        with pytest.raises(quick.Again):
            send(step=4)
        # Another device may.
        send(address="203.0.113.99", step=4, reasons=("fast_traffic",))
        monkeypatch.setattr(quick, "DAILY_MAX", 2)
        send(way=OTHER_ROAD, step=3, reasons=("heavy_traffic",))
        SignedOutSend.objects.create(device=quick.device_hash(ADDRESS), osm_way_id=1)
        with pytest.raises(quick.Limited) as limited:
            send(way=6002, step=3, reasons=("heavy_traffic",), address=ADDRESS)
        assert limited.value.status == 429

    def test_counts_older_than_a_day_are_deleted(self, live) -> None:
        old = SignedOutSend.objects.create(
            device="x" * 64, osm_way_id=1, created_at=timezone.now() - timedelta(hours=25)
        )
        send()
        assert not SignedOutSend.objects.filter(pk=old.pk).exists()

    def test_half_steps_and_avoid_are_levels_too(self, live) -> None:
        avoid = send(step=5, reasons=("fast_traffic",))
        assert (avoid.tier, avoid.half) == (5, False)


@db
class TestReview:
    def test_sends_for_a_road_come_together_with_how_many_agree(self, live) -> None:
        send(address="203.0.113.1", step=2, reasons=("calmer",))
        send(address="203.0.113.2", step=2, reasons=("calmer",))
        send(address="203.0.113.3", step=4, reasons=("fast_traffic",))
        send(address="203.0.113.4", way=OTHER_ROAD, step=3, reasons=("heavy_traffic",))
        listed = suggestions.open_suggestions()
        assert [(s.osm_way_id, s.agree) for s in listed] == [
            (WAY, 2),
            (WAY, 2),
            (WAY, 1),
            (OTHER_ROAD, 1),
        ]
        row = suggestions.summary(listed[0])
        assert row["signed_out"] and row["reasons"] == ["calmer"] and row["agree"] == 2

    def test_the_two_agreeing_threshold_is_built_but_off(self, live, settings) -> None:
        send(address="203.0.113.1", step=2)
        assert len(suggestions.open_suggestions()) == 1
        settings.SUGGEST_SIGNED_OUT_MIN_AGREE = 2
        assert suggestions.open_suggestions() == []
        send(address="203.0.113.2", step=2)
        assert [s.agree for s in suggestions.open_suggestions()] == [2, 2]

    def test_hidden_signed_out_sends_do_not_fill_the_window(
        self, live, settings, monkeypatch
    ) -> None:
        """Under a raised minimum, old lone signed-out sends never show, so they must not use up
        the rows read before grouping and keep a newer signed-in suggestion out of the queue."""
        settings.SUGGEST_SIGNED_OUT_MIN_AGREE = 2
        monkeypatch.setattr(suggestions, "OPEN_READ", 2)
        send(address="203.0.113.1", step=2)
        send(address="203.0.113.2", way=OTHER_ROAD, step=3)
        rider = StressSuggestion.objects.create(
            suggester=make_user(),
            osm_way_id=OTHER_ROAD + 1,
            lat=38.9,
            lon=-77.0,
            current_tier=3,
            tier=2,
            reason="Quiet in the mornings.",
        )
        assert [s.pk for s in suggestions.open_suggestions()] == [rider.pk]

    def test_an_admin_approves_a_signed_out_suggestion_as_any_other(self, live) -> None:
        found = send(step=2)
        approved, _result = suggestions.approve(make_user(), found.pk)
        assert approved.status == StressSuggestion.Status.APPROVED
