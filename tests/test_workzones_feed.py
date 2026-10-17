"""The work-zone feeds' shared copy and the planner's use of it (core.workzones,
FOLLOWUP-WORKZONES). The network is a fake; the database is real."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_route_api import segments  # noqa: F401 - the live segment table, a fixture

from core import workzones
from core.models import BikeshareFeedCache
from routemaker import workzones as wz

db = pytest.mark.django_db(transaction=True)

SAMPLE = (
    Path(__file__).resolve().parent / "data" / "workzones" / "wzdx-v4-sample.geojson"
).read_bytes()
NOW = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)
KEY = "not-a-real-key-0123"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(workzones.TOKEN_ENV, raising=False)
    workzones.forget()
    yield
    workzones.forget()


class Feeds:
    """Answers each URL from `answers` (bytes, or an exception), recording the URLs."""

    def __init__(self, **answers) -> None:
        self.answers = answers
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.urls.append(url)
        source = "va" if "iteriscloud" in url else "md"
        answer = self.answers[source]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def no_sleep(_s: float) -> None:
    pass


@db
class TestRefresh:
    def test_maryland_is_read_without_a_key_and_virginia_not_at_all(self) -> None:
        feeds = Feeds(md=SAMPLE)
        line = workzones.refresh(feeds, no_sleep, lambda: NOW)
        assert feeds.urls == [workzones.FEEDS["md"]]
        assert line == "work zones: md 5 zones"
        stored = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]
        assert set(stored) == {"md"} and len(stored["md"]["zones"]) == 5

    def test_virginia_with_the_key_and_the_key_is_never_logged(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv(workzones.TOKEN_ENV, KEY)
        feeds = Feeds(md=SAMPLE, va=[workzones.FeedError("HTTP 503")] * 3)
        # Virginia has never been read, so the run fails, with Maryland's zones saved (OPS-3).
        with pytest.raises(workzones.FeedError) as failed:
            workzones.refresh(feeds, no_sleep, lambda: NOW)
        line = str(failed.value)
        assert f"token={KEY}" in feeds.urls[-1]
        assert len([u for u in feeds.urls if "iteriscloud" in u]) == workzones.TRIES
        assert line == "work zones: md 5 zones, va failed; no good read in 20 minutes: va"
        assert KEY not in caplog.text and KEY not in line
        stored = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]
        assert len(stored["md"]["zones"]) == 5

    def test_a_failed_read_keeps_the_last_good_copy(self) -> None:
        workzones.refresh(Feeds(md=SAMPLE), no_sleep, lambda: NOW)
        later = NOW + timedelta(minutes=5)
        workzones.refresh(Feeds(md=[ValueError("bad json")] * 3), no_sleep, lambda: later)
        feed = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]["md"]
        assert feed["read_at"] == NOW.isoformat() and feed["failed_at"] == later.isoformat()
        assert len(feed["zones"]) == 5
        # Still failing past the twenty minutes: the copy is kept and the run fails (OPS-3).
        much_later = NOW + timedelta(minutes=21)
        with pytest.raises(workzones.FeedError, match="no good read in 20 minutes: md"):
            workzones.refresh(Feeds(md=[ValueError("bad json")] * 3), no_sleep, lambda: much_later)
        feed = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]["md"]
        assert feed["failed_at"] == much_later.isoformat() and len(feed["zones"]) == 5

    def test_a_retry_that_succeeds(self) -> None:
        feeds = Feeds(md=[workzones.FeedError("TimeoutError"), SAMPLE])
        assert workzones.refresh(feeds, no_sleep, lambda: NOW) == "work zones: md 5 zones"


@db
class TestSnapshot:
    def test_current_stale_and_unavailable(self) -> None:
        workzones.refresh(Feeds(md=SAMPLE), no_sleep, lambda: NOW)
        assert workzones._load(NOW + timedelta(minutes=10)).status == {"md": "current"}
        assert workzones._load(NOW + timedelta(minutes=30)).status == {"md": "stale"}
        late = workzones._load(NOW + timedelta(hours=3))
        assert late.status == {"md": "unavailable"} and late.zones == ()

    def test_never_refreshed_is_not_running_and_says_nothing(self) -> None:
        assert workzones._load(NOW).status == {}
        assert workzones.plan_zones([(-77.03, 38.95), (-77.03, 38.96)], "weekend") is None

    def test_a_feed_that_never_read_well_is_unavailable(self) -> None:
        with pytest.raises(workzones.FeedError):  # the run fails, the row is still written
            workzones.refresh(Feeds(md=[ValueError("bad")] * 3), no_sleep, lambda: NOW)
        assert workzones._load(NOW).status == {"md": "unavailable"}

    def test_the_api_goes_by_what_the_worker_stored_not_its_own_key(self, monkeypatch) -> None:
        monkeypatch.setenv(workzones.TOKEN_ENV, KEY)
        workzones.refresh(Feeds(md=SAMPLE, va=SAMPLE), no_sleep, lambda: NOW)
        monkeypatch.delenv(workzones.TOKEN_ENV)  # the API service holds no key
        found = workzones._load(NOW)
        assert found.status == {"md": "current", "va": "current"}
        assert len(found.zones) == 10


def test_the_ride_moment_is_now_when_the_dial_is_on_now() -> None:
    from routemaker import ridetime

    now = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # a Tuesday, 11:00 in Washington
    assert workzones.ride_moment(ridetime.when_at(now), now) == now
    weekend = workzones.ride_moment(ridetime.WEEKEND, now)
    assert weekend.weekday() == 5 and weekend > now


def trip(points, seconds) -> dict:
    """A router answer whose one leg runs through `points`."""
    from core.dedodge import encode_polyline6

    return {
        "trip": {
            "legs": [{"shape": encode_polyline6(points)}],
            "summary": {"time": seconds},
        }
    }


ZONES = {z.zone_id: z for z in wz.parse_feed(json.loads(SAMPLE), "md")}
FLAGGED = [(-77.0700, 38.9880), (-77.0700, 38.9950)]  # along the flagger zone (+180 s)


class TestPenalties:
    def plan(self) -> wz.PlanZones:
        return wz.PlanZones(status={"md": "current"}, passable=[ZONES["md-wz-flagger"]])

    def test_the_way_round_is_taken_when_it_costs_less_than_the_penalty(self) -> None:
        plan, request, asked = self.plan(), {"locations": []}, []

        def reroute(r):
            asked.append(r)
            return trip([(-77.0710, 38.9880), (-77.0710, 38.9950)], 400 + 170)

        chosen = workzones.settle_penalties(trip(FLAGGED, 400), request, plan, reroute, lambda: 30)
        assert chosen["trip"]["summary"]["time"] == 570
        (ring,) = asked[0]["exclude_polygons"]
        assert request["exclude_polygons"] == [ring]  # later searches leave it out too
        assert [z.zone_id for z in plan.avoided] == ["md-wz-flagger"]

    def test_the_zone_is_ridden_when_the_way_round_costs_more(self) -> None:
        plan, request = self.plan(), {"locations": []}
        first = trip(FLAGGED, 400)
        chosen = workzones.settle_penalties(
            first, request, plan, lambda r: trip(FLAGGED, 400 + 181), lambda: 30
        )
        assert chosen is first and "exclude_polygons" not in request and plan.avoided == []

    def test_no_reroute_when_the_route_misses_every_zone_or_time_is_short(self) -> None:
        def reroute(_r):
            raise AssertionError("not asked")

        away = trip([(-77.1, 38.9), (-77.1, 38.91)], 400)
        assert workzones.settle_penalties(away, {}, self.plan(), reroute, lambda: 30) is away
        near = trip(FLAGGED, 400)
        assert workzones.settle_penalties(near, {}, self.plan(), reroute, lambda: 1) is near

    def test_a_refusal_keeps_the_first_route(self) -> None:
        def reroute(_r):
            raise RuntimeError("no path")

        first = trip(FLAGGED, 400)
        assert workzones.settle_penalties(first, {}, self.plan(), reroute, lambda: 30) is first


class TestTheAnswer:
    def body(self) -> dict:
        return {
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in FLAGGED]},
            "distance_m": 778.0,
            "description": [{"kind": "stretch", "from_m": 0, "text": "Ride north."}],
            "description_overview": None,
        }

    def test_a_heads_up_in_route_order_with_the_disclaimer(self) -> None:
        plan = wz.PlanZones(status={"md": "current"}, passable=[ZONES["md-wz-flagger"]])
        body = workzones.with_work_zones(self.body(), plan)
        texts = [e["text"] for e in body["description"]]
        assert texts[0] == wz.DISCLAIMER
        assert texts[1] == "Ride north."
        assert texts[2].startswith("Work zone ahead on Country Lane, ")
        assert body["description"][2]["citation"].startswith("Source: Maryland DOT SHA")
        assert body["description"][2]["severity"] == "orange"
        assert body["description_overview"] is None
        summary = body["work_zones"]
        assert [z["id"] for z in summary["on_route"]] == ["md-wz-flagger"]
        assert summary["on_route"][0]["penalty_s"] == 180 and not summary["on_route"][0]["warning"]
        assert summary["sources"] == ["Maryland DOT SHA work zones (WZDx, CC0)"]
        assert summary["unchecked"] is None

    def test_a_stale_feed_is_labelled_and_an_unavailable_one_said(self) -> None:
        plan = wz.PlanZones(
            status={"md": "stale", "va": "unavailable"}, passable=[ZONES["md-wz-flagger"]]
        )
        body = workzones.with_work_zones(self.body(), plan)
        texts = [e["text"] for e in body["description"]]
        cited = [e.get("citation") or "" for e in body["description"]]
        assert any(c.endswith(workzones.STALE_NOTE) for c in cited)
        assert (
            "Work zones could not be checked for this route: Virginia's feed not available."
            in texts
        )
        assert body["work_zones"]["stale"] == ["Maryland's feed"]

    def test_no_zone_no_entry(self) -> None:
        body = workzones.with_work_zones(self.body(), wz.PlanZones(status={"md": "current"}))
        assert [e["text"] for e in body["description"]] == ["Ride north."]
        assert body["work_zones"]["on_route"] == []


# --- Through the route endpoint -------------------------------------------------


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_a_plan_leaves_out_a_closure_and_goes_round_a_penalty_zone_worth_it(
    client, monkeypatch
) -> None:
    """The stored zones reach the router's requests: the closure to bicycles as an
    `exclude_polygons` strip on the first request, the flagger zone the route runs along
    added on the second, kept because the way round costs less than its 180 s; and the
    answer says so."""
    from test_route_api import VERTICES, FakeRouter, good_body, post, route_answer, trace_answer

    from core import routing

    side = ((-77.045, 38.905), (-77.045, 38.910))
    main = ((-77.04, 38.9), (-77.035, 38.9))
    # An end date: a closure with none "may still apply" on a later ride and is not routed
    # round (v0.7.0), and the suite's clock may make this ride a later one.
    until = datetime.now(UTC) + timedelta(days=30)
    closed = wz.Zone("md-c", "md", wz.CLOSED, 0, side, "Side Road", None, None, until)
    flagger = wz.Zone("md-f", "md", wz.PENALTY, 180, main, "Main Road", None, None, None)
    BikeshareFeedCache.objects.create(
        key=workzones.KEY,
        payload={
            "feeds": {
                "md": {
                    # The real clock: the suite's `weekday_clock` moves Django's.
                    "read_at": datetime.now(UTC).isoformat(),
                    "zones": [closed.to_json(), flagger.to_json()],
                }
            }
        },
        fetched_at=datetime.now(UTC),
    )
    first = route_answer([(VERTICES, 2.2, [10.0] * 5)])
    round_it = route_answer([(VERTICES, 2.2, [10.0] * 5)])
    round_it["trip"]["summary"]["time"] = 220.0 + 170.0
    fake = FakeRouter(
        {
            "route": [first, round_it] + [round_it] * 20,
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    sent: list[dict] = []

    def transport(url, payload, timeout):
        # As sent: the plan goes on to change its request in place.
        sent.append({"url": url, **json.loads(json.dumps(payload))})
        return fake(url, payload, timeout)

    monkeypatch.setattr(routing, "_transport", transport)
    response = post(client, good_body())
    assert response.status_code == 200, response.content
    routes = [payload for payload in sent if payload["url"].endswith("/route")]
    assert len(routes[0]["exclude_polygons"]) == 1
    assert len(routes[1]["exclude_polygons"]) == 2
    body = response.json()
    assert body["work_zones"]["routed_round"] == 2
    assert body["work_zones"]["status"] == {"md": "current"}
    # The fake answers the same line, so the flagger zone is still under it, and said.
    assert [z["id"] for z in body["work_zones"]["on_route"]] == ["md-f"]
    assert any(e["kind"] == "workzone" and e["severity"] == "orange" for e in body["description"])


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_no_way_round_a_closure_plans_through_it_with_a_red_warning(client, monkeypatch) -> None:
    """Where the router finds no route round a zone closed to bicycles, the plan goes
    through it, warned of in red, rather than answering no route."""
    from test_route_api import VERTICES, FakeRouter, good_body, post, route_answer, trace_answer

    from core import routing

    across = ((-77.04, 38.9), (-77.035, 38.9))  # under the route itself
    until = datetime.now(UTC) + timedelta(days=30)
    closed = wz.Zone("md-c", "md", wz.CLOSED, 0, across, "Main Road", None, None, until)
    BikeshareFeedCache.objects.create(
        key=workzones.KEY,
        payload={"feeds": {"md": {"read_at": datetime.now(UTC).isoformat(),
                                  "zones": [closed.to_json()]}}},
    )  # fmt: skip
    fake = FakeRouter(
        {
            "route": [routing.RouterRefused(400, 442, "No path could be found for input")]
            + [route_answer([(VERTICES, 2.2, [10.0] * 5)])] * 20,
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.2)]),
        }
    )
    sent: list[dict] = []

    def transport(url, payload, timeout):
        sent.append({"url": url, **json.loads(json.dumps(payload))})
        return fake(url, payload, timeout)

    monkeypatch.setattr(routing, "_transport", transport)
    response = post(client, good_body())
    assert response.status_code == 200, response.content
    routes = [p for p in sent if p["url"].endswith("/route")]
    assert "exclude_polygons" in routes[0] and "exclude_polygons" not in routes[1]
    body = response.json()
    (zone,) = body["work_zones"]["on_route"]
    assert zone["kind"] == "closed" and zone["warning"]
    assert body["work_zones"]["routed_round"] == 0
    red = [e for e in body["description"] if e["kind"] == "workzone" and e["severity"] == "red"]
    assert red and red[0]["text"] == "Main Road marked closed ahead."
    assert red[0]["citation"].startswith("Source: Maryland DOT SHA work zones")


class TestTheRealFetchNeverRepeatsTheKey:
    """`http_get`, the real fetch: every failure is a FeedError naming only its kind,
    so the key in the URL never reaches a log or a run row (346: "the key stays
    server-side only"), and one feed's failure is never the whole refresh's."""

    def test_a_refused_connection(self) -> None:
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with pytest.raises(workzones.FeedError) as caught:
            workzones.http_get(f"http://127.0.0.1:{port}/feed?token={KEY}", 2.0)
        assert KEY not in str(caught.value) and "127.0.0.1" not in str(caught.value)

    def test_a_url_http_client_refuses_names_no_part_of_it(self) -> None:
        # http.client.InvalidURL repeats the whole URL in its message.
        with pytest.raises(workzones.FeedError) as caught:
            workzones.http_get(f"http://127.0.0.1:1/feed?token={KEY} x", 2.0)
        assert KEY not in str(caught.value) and str(caught.value) == "InvalidURL"

    def test_an_http_error_is_its_status(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Down(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - the http.server name
                self.send_response(503)
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Down)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with pytest.raises(workzones.FeedError) as caught:
                workzones.http_get(f"http://127.0.0.1:{server.server_port}/?token={KEY}", 5.0)
        finally:
            server.shutdown()
        assert str(caught.value) == "HTTP 503"


@db
def test_the_work_zones_row_and_the_bikeshare_row_share_the_table_apart() -> None:
    """The zones live in `bikeshare_feed_cache` under their own key (no migration): the
    GBFS store neither reads nor overwrites them, and they do not touch its row."""
    from core import gbfs

    assert workzones.KEY == BikeshareFeedCache.WORKZONES != BikeshareFeedCache.CURRENT
    workzones.refresh(Feeds(md=SAMPLE), no_sleep, lambda: NOW)
    store = gbfs.DatabaseStore()
    assert store.load() is None, "the bikeshare store sees no feed of its own yet"
    store.mark_failed(NOW.timestamp())
    keys = set(BikeshareFeedCache.objects.values_list("key", flat=True))
    assert keys == {BikeshareFeedCache.CURRENT, BikeshareFeedCache.WORKZONES}
    zones = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]["md"]["zones"]
    assert len(zones) == 5
