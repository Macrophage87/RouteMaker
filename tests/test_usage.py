"""Anonymous daily usage totals (core.usage; the owner, 2026-11-13: "Yes to anonymous data
totals"): a day, a tool's name and a count, and nothing that says who, where or when in the day."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import resolve
from test_accounts import addr
from test_connector import mcp, tokens_for

from core import usage
from core.models import DailyUsage


def totals() -> dict[str, int]:
    return {row.tool: row.count for row in DailyUsage.objects.all()}


def test_a_row_holds_only_the_day_the_tool_and_the_count() -> None:
    fields = {f.name for f in DailyUsage._meta.get_fields()}
    assert fields == {"id", "day", "tool", "count"}


def test_the_day_is_washington_s_not_utc() -> None:
    # 1:30 AM UTC on the 14th is 8:30 PM on the 13th in Washington.
    assert str(usage.today(datetime(2026, 11, 14, 1, 30, tzinfo=UTC))) == "2026-11-13"


@pytest.mark.django_db
def test_each_use_adds_one_to_today_s_total_for_its_tool() -> None:
    usage.tally("plan route")
    usage.tally("plan route")
    usage.tally("search")
    assert totals() == {"plan route": 2, "search": 1}
    assert {row.day for row in DailyUsage.objects.all()} == {usage.today()}


def test_every_counted_route_is_one_the_site_answers() -> None:
    for _method, route in usage.ROUTES:
        path = "/" + route.replace("<ride_id>", "r1")
        assert resolve(path).route == route


def _through_middleware(method: str, path: str, status: int) -> None:
    request = getattr(RequestFactory(), method.lower())(path)

    def view(request):
        request.resolver_match = resolve(path)
        return HttpResponse(status=status)

    usage.UsageMiddleware(view)(request)


@pytest.mark.django_db
def test_only_a_successful_answer_from_a_listed_route_is_counted() -> None:
    _through_middleware("POST", "/api/route", 200)
    _through_middleware("POST", "/api/route", 429)  # refused: not a use
    _through_middleware("GET", "/api/route", 200)  # not the planning method
    _through_middleware("POST", "/api/rides/r1/here", 200)  # a ride's repeated position post
    _through_middleware("GET", "/api/geocode", 200)
    assert totals() == {"plan route": 1, "place search requests": 1}


@pytest.mark.django_db
def test_a_ride_started_is_counted_by_its_kind_only() -> None:
    client = Client()
    for tool in ("ride", "ride", "walk"):
        r = client.post("/api/usage", {"tool": tool}, content_type="application/json", **addr())
        assert r.status_code == 204
    bad = client.post("/api/usage", {"tool": "home"}, content_type="application/json", **addr())
    assert bad.status_code == 400
    assert totals() == {"ride": 2, "walk": 1}


@pytest.mark.django_db
def test_a_count_from_another_site_is_refused() -> None:
    r = Client().post(
        "/api/usage",
        {"tool": "ride"},
        content_type="application/json",
        HTTP_SEC_FETCH_SITE="cross-site",
        **addr(),
    )
    assert r.status_code == 403
    assert totals() == {}


@pytest.mark.django_db
def test_a_connector_tool_call_adds_to_one_total_and_test_calls_do_not() -> None:
    _user, token, _client_id = tokens_for()
    mcp(token["access_token"], "tools/call", {"name": "my_drafts", "arguments": {}})
    mcp(token["access_token"], "tools/call", {"name": "not_a_tool", "arguments": {}})
    mcp(token["access_token"], "tools/call", {"name": "my_drafts", "arguments": {"test": True}})
    mcp(token["access_token"], "tools/list")
    assert totals() == {usage.CONNECTOR: 1}


@pytest.mark.django_db
def test_the_privacy_policy_says_what_is_counted() -> None:
    from core import privacy_policy

    page = Client().get("/privacy").content.decode()
    assert "no route, place" in privacy_policy.USAGE_TOTALS
    assert "each tool is used each day" in page


@pytest.mark.django_db
def test_a_count_that_fails_never_breaks_the_answer(monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise DatabaseError("down")

    monkeypatch.setattr(usage.connection, "cursor", broken)
    request = RequestFactory().post("/api/route")

    def view(request):
        request.resolver_match = resolve("/api/route")
        return HttpResponse(status=200)

    assert usage.UsageMiddleware(view)(request).status_code == 200


def test_nothing_on_a_ride_link_is_counted() -> None:
    # The ride endpoints write nothing to the database (tests/test_ride_presence.py).
    assert not [route for _method, route in usage.ROUTES if route.startswith("api/rides/")]
