"""GET /api/geocode and GET /api/reverse: signed-out place search and place names.

Photon is replaced by a fake at the one function that touches the network
(`core.geocode._get`), so these tests see exactly what the API would have asked
Photon for and control what comes back. `_get` itself is tested against a real
local HTTP server at the bottom. The limiter is the real one, on the real
database.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import urllib.parse

import pytest
from django.conf import settings
from django.db import connection
from django.test import override_settings
from test_ratelimit import in_one_window
from test_route_api import hold_slots

from core import geocode, ratelimit

db = pytest.mark.django_db(transaction=True)

SEARCH = "/api/geocode"
REVERSE = "/api/reverse"
PLACE_KEYS = {"name", "label", "lon", "lat", "kind"}

INSIDE = (-77.0502, 38.8893)  # the Lincoln Memorial
OUTSIDE = (-80.0, 40.44)  # Pittsburgh


def feature(lon, lat, **properties) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def answer(*features) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


LINCOLN = feature(
    *INSIDE,
    name="Lincoln Memorial",
    type="house",
    osm_key="tourism",
    osm_value="attraction",
    city="Washington",
    state="District of Columbia",
    street="Lincoln Memorial Circle Northwest",
    housenumber="2",
)


class FakePhoton:
    """Records every call; answers `reply` (a body or an exception to raise)."""

    def __init__(self, reply) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict) -> dict:
        self.calls.append((path, dict(params)))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def photon(monkeypatch):
    def install(reply) -> FakePhoton:
        fake = FakePhoton(reply)
        monkeypatch.setattr(geocode, "_get", fake)
        return fake

    return install


_next = iter(range(1, 250))


def fresh_client() -> dict:
    """A client address of its own, so one test's count is not another's."""
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_next)}"}


def get(client, path, headers=None, **params):
    return client.get(path, params, **(headers or fresh_client()))


@db
class TestSearch:
    def test_an_answer_is_a_short_list_with_attribution(self, client, photon) -> None:
        photon(answer(LINCOLN))
        response = get(client, SEARCH, q="Lincoln Memorial")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"results", "attribution"}
        assert len(body["results"]) == 1
        place = body["results"][0]
        assert set(place) == PLACE_KEYS
        assert (place["lon"], place["lat"]) == pytest.approx(INSIDE)
        assert "Lincoln Memorial" in place["name"]
        assert "Washington" in place["label"]
        assert any("OpenStreetMap" in line for line in body["attribution"])

    def test_every_search_is_fenced_to_the_coverage_box(self, client, photon) -> None:
        fake = photon(answer())
        get(client, SEARCH, q="Union Station")
        ((path, params),) = fake.calls
        assert path == "/api"
        west, south, east, north = settings.COVERAGE_BBOX
        assert [float(x) for x in params["bbox"].split(",")] == [west, south, east, north]

    def test_a_result_outside_the_box_is_dropped(self, client, photon) -> None:
        photon(answer(feature(*OUTSIDE, name="Union Station", type="other"), LINCOLN))
        results = get(client, SEARCH, q="station").json()["results"]
        assert [(r["lon"], r["lat"]) for r in results] == [pytest.approx(INSIDE)]

    def test_nothing_but_the_named_parameters_reaches_photon(self, client, photon) -> None:
        """Not an open proxy: whatever else the request carries, Photon is
        asked for the query, the bias, the count, the language and the box."""
        fake = photon(answer())
        get(
            client,
            SEARCH,
            q="Purcellville",
            lat="39.1",
            lon="-77.5",
            limit="3",
            osm_tag="amenity:bar",
            bbox="-180,-90,180,90",
            layer="house",
            debug="1",
            url="http://elsewhere.example/",
        )
        ((_path, params),) = fake.calls
        assert set(params) == {"q", "lat", "lon", "limit", "lang", "bbox"}
        assert params["q"] == "Purcellville"
        assert (params["lat"], params["lon"], params["limit"]) == (39.1, -77.5, 3)
        assert params["bbox"] != "-180,-90,180,90"

    def test_without_a_bias_none_is_sent(self, client, photon) -> None:
        fake = photon(answer())
        get(client, SEARCH, q="Purcellville")
        ((_path, params),) = fake.calls
        assert "lat" not in params and "lon" not in params

    def test_whitespace_is_collapsed_before_it_is_sent(self, client, photon) -> None:
        fake = photon(answer())
        get(client, SEARCH, q="  union \t  station ")
        assert fake.calls[0][1]["q"] == "union station"

    def test_no_more_results_than_asked_for(self, client, photon) -> None:
        many = [feature(-77.0 - i / 1000, 38.9, name=f"Place {i}", type="other") for i in range(8)]
        photon(answer(*many))
        assert len(get(client, SEARCH, q="place", limit="3").json()["results"]) == 3

    def test_the_same_label_twice_is_shown_once(self, client, photon) -> None:
        """Photon returns a long street once per way; a list of five identical
        lines is no use to anyone."""
        street = dict(name="Wilson Boulevard", type="street", city="Arlington")
        photon(answer(feature(-77.1, 38.88, **street), feature(-77.09, 38.881, **street)))
        assert len(get(client, SEARCH, q="wilson blvd").json()["results"]) == 1

    @pytest.mark.parametrize(
        "params",
        [
            {"q": "a"},
            {"q": "   "},
            {"q": "x" * 201},
            {},
            {"q": "station", "lat": "38.9"},
            {"q": "station", "lon": "-77.0"},
            {"q": "station", "lat": str(OUTSIDE[1]), "lon": str(OUTSIDE[0])},
            {"q": "station", "lat": "nan", "lon": "-77.0"},
            {"q": "station", "limit": "0"},
            {"q": "station", "limit": str(geocode.MAX_RESULTS + 1)},
            {"q": "station", "lang": "de"},
        ],
    )
    def test_input_it_will_not_search_is_400_and_photon_is_not_asked(
        self, client, photon, params
    ) -> None:
        fake = photon(answer())
        response = get(client, SEARCH, **params)
        assert response.status_code == 400
        assert set(response.json()) == {"error"}
        assert fake.calls == []

    def test_a_geocoder_that_does_not_answer_is_502(self, client, photon) -> None:
        photon(geocode.Unavailable("connection refused"))
        response = get(client, SEARCH, q="Union Station")
        assert response.status_code == 502
        assert set(response.json()) == {"error"}

    def test_an_answer_may_be_kept_by_the_browser_only(self, client, photon) -> None:
        photon(answer(LINCOLN))
        cache = get(client, SEARCH, q="Lincoln").get("Cache-Control", "")
        assert "private" in cache and "max-age=" in cache


def rows(scope: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM rate_limit_window WHERE scope = %s", [scope])
        return cursor.fetchone()[0]


def spend(limit: ratelimit.Limit, address: str, hits: int) -> None:
    key = ratelimit.client_key(address)
    for _ in range(hits):
        ratelimit.hit(limit, key)


@db
class TestLimits:
    def test_the_limits_are_the_plans_typeahead_figures(self) -> None:
        """PLAN.md:65: "roughly 5 requests per second burst and 60 per minute"."""
        assert (ratelimit.GEOCODE_BURST.requests, ratelimit.GEOCODE_BURST.window_s) == (5, 1)
        assert (ratelimit.GEOCODE.requests, ratelimit.GEOCODE.window_s) == (60, 60)
        assert ratelimit.REVERSE.requests == 60

    def test_a_plan_of_twenty_five_points_can_be_named_at_once(self) -> None:
        """A shared link opens with up to 25 points, and each is named."""
        from core.api import MAX_POINTS

        assert ratelimit.REVERSE_BURST.requests >= MAX_POINTS
        assert ratelimit.REVERSE.requests >= MAX_POINTS

    def test_the_sixth_search_in_a_second_is_429(self, client, photon) -> None:
        fake = photon(answer())

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"203.0.113.{10 + n}"}
            statuses = [
                get(client, SEARCH, headers, q="station").status_code
                for _ in range(ratelimit.GEOCODE_BURST.requests)
            ]
            asked = len(fake.calls)
            return statuses, asked, get(client, SEARCH, headers, q="station")

        statuses, asked, refused = in_one_window(ratelimit.GEOCODE_BURST.window_s, attempt)
        assert statuses == [200] * ratelimit.GEOCODE_BURST.requests
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= ratelimit.GEOCODE_BURST.window_s
        assert len(fake.calls) == asked

    def test_a_spent_minute_is_429_and_another_address_is_not(self, client, photon) -> None:
        fake = photon(answer())

        def attempt(n):
            address = f"203.0.113.{20 + n}"
            spend(ratelimit.GEOCODE, address, ratelimit.GEOCODE.requests)
            refused = get(client, SEARCH, {"HTTP_X_FORWARDED_FOR": address}, q="station")
            return refused, len(fake.calls)

        refused, asked = in_one_window(ratelimit.GEOCODE.window_s, attempt)
        assert refused.status_code == 429
        assert asked == 0
        assert get(client, SEARCH, q="station").status_code == 200

    def test_a_burst_refusal_does_not_spend_the_minute(self, client, photon) -> None:
        photon(answer())

        def attempt(n):
            address = f"203.0.113.{30 + n}"
            spend(ratelimit.GEOCODE_BURST, address, ratelimit.GEOCODE_BURST.requests)
            refused = get(client, SEARCH, {"HTTP_X_FORWARDED_FOR": address}, q="station")
            return refused

        assert in_one_window(ratelimit.GEOCODE_BURST.window_s, attempt).status_code == 429
        assert rows(ratelimit.GEOCODE.scope) == 0

    def test_search_and_names_are_counted_apart(self, client, photon) -> None:
        """Naming a plan's points must not spend the search box's budget."""
        photon(answer())

        def attempt(n):
            address = f"203.0.113.{40 + n}"
            headers = {"HTTP_X_FORWARDED_FOR": address}
            spend(ratelimit.GEOCODE, address, ratelimit.GEOCODE.requests)
            return get(client, REVERSE, headers, lat=INSIDE[1], lon=INSIDE[0]).status_code

        assert in_one_window(ratelimit.GEOCODE.window_s, attempt) == 200

    def test_a_spent_reverse_minute_is_429(self, client, photon) -> None:
        photon(answer())

        def attempt(n):
            address = f"203.0.113.{50 + n}"
            spend(ratelimit.REVERSE, address, ratelimit.REVERSE.requests)
            headers = {"HTTP_X_FORWARDED_FOR": address}
            return get(client, REVERSE, headers, lat=INSIDE[1], lon=INSIDE[0]).status_code

        assert in_one_window(ratelimit.REVERSE.window_s, attempt) == 429

    @pytest.mark.parametrize("site", ["cross-site", "same-site"])
    def test_a_foreign_page_cannot_spend_the_budget(self, client, photon, site) -> None:
        """Any page can make a visitor's browser send a GET here; the browser
        says so in Sec-Fetch-Site, and such a request is refused uncounted."""
        fake = photon(answer())
        headers = {**fresh_client(), "HTTP_SEC_FETCH_SITE": site}
        for path, params in ((SEARCH, {"q": "station"}), (REVERSE, dict(lat=38.9, lon=-77.0))):
            response = get(client, path, headers, **params)
            assert response.status_code == 403
            assert set(response.json()) == {"error"}
        assert fake.calls == []
        assert rows(ratelimit.GEOCODE_BURST.scope) == 0
        assert rows(ratelimit.REVERSE_BURST.scope) == 0

    @pytest.mark.parametrize("site", ["same-origin", "none"])
    def test_this_sites_own_pages_are_answered(self, client, photon, site) -> None:
        photon(answer())
        headers = {**fresh_client(), "HTTP_SEC_FETCH_SITE": site}
        assert get(client, SEARCH, headers, q="station").status_code == 200

    def test_a_client_already_searching_is_429(self, client, photon) -> None:
        photon(answer())
        address = "203.0.113.60"
        limit = ratelimit.GEOCODE_IN_FLIGHT
        key = ratelimit._client_lock_id(ratelimit.client_key(address))
        other = hold_slots([(ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64, key)])
        try:
            refused = get(client, SEARCH, {"HTTP_X_FORWARDED_FOR": address}, q="station")
        finally:
            other.close()
        assert refused.status_code == 429
        assert int(refused["Retry-After"]) >= 1

    @override_settings(GEOCODE_CONCURRENCY=1)
    def test_a_busy_geocoder_is_503_and_holds_no_worker(self, client, photon) -> None:
        fake = photon(answer())
        limit = ratelimit.GEOCODE_IN_FLIGHT
        other = hold_slots([(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, 0)])
        try:
            refused = get(client, REVERSE, lat=INSIDE[1], lon=INSIDE[0])
        finally:
            other.close()
        assert refused.status_code == 503
        assert int(refused["Retry-After"]) >= 1
        assert fake.calls == []


@db
class TestReverse:
    def test_a_point_is_named_by_what_it_is_on(self, client, photon) -> None:
        fake = photon(
            answer(
                feature(
                    -77.0869,
                    38.8870,
                    type="house",
                    housenumber="3100",
                    street="Wilson Boulevard",
                    district="Clarendon",
                    city="Arlington",
                )
            )
        )
        response = get(client, REVERSE, lat="38.887", lon="-77.0869")
        assert response.status_code == 200
        (place,) = response.json()["results"]
        assert set(place) == PLACE_KEYS
        assert place["name"] == "Wilson Boulevard"
        assert "3100" not in place["label"]
        assert "Clarendon" in place["label"] or "Arlington" in place["label"]
        ((path, params),) = fake.calls
        assert path == "/reverse"
        assert set(params) == {"lat", "lon", "lang", "limit", "radius"}
        assert params["limit"] == 1

    def test_a_named_place_keeps_its_name(self, client, photon) -> None:
        photon(answer(LINCOLN))
        (place,) = get(client, REVERSE, lat=INSIDE[1], lon=INSIDE[0]).json()["results"]
        assert place["name"] == "Lincoln Memorial"

    def test_nothing_nearby_is_an_empty_list(self, client, photon) -> None:
        photon(answer())
        response = get(client, REVERSE, lat=INSIDE[1], lon=INSIDE[0])
        assert response.status_code == 200
        assert response.json()["results"] == []

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"lat": "38.9"},
            {"lat": str(OUTSIDE[1]), "lon": str(OUTSIDE[0])},
            {"lat": "inf", "lon": "-77"},
            {"lat": "38.9", "lon": "-77", "lang": "fr"},
        ],
    )
    def test_a_point_it_will_not_name_is_400(self, client, photon, params) -> None:
        fake = photon(answer())
        assert get(client, REVERSE, **params).status_code == 400
        assert fake.calls == []

    def test_a_geocoder_that_does_not_answer_is_502(self, client, photon) -> None:
        photon(geocode.Unavailable("timed out"))
        assert get(client, REVERSE, lat=INSIDE[1], lon=INSIDE[0]).status_code == 502


class TestDescribe:
    def test_a_searched_address_keeps_its_house_number(self) -> None:
        name, label = geocode.describe(
            {"type": "house", "housenumber": "1000", "street": "N Glebe Rd", "city": "Arlington"},
            reverse=False,
        )
        assert name == "1000 N Glebe Rd"
        assert label == "1000 N Glebe Rd, Arlington"

    def test_a_named_place_is_its_name_then_where(self) -> None:
        name, label = geocode.describe(
            {
                "type": "house",
                "name": "Union Station",
                "street": "Massachusetts Avenue NE",
                "housenumber": "50",
                "city": "Washington",
                "state": "District of Columbia",
            },
            reverse=False,
        )
        assert name == "Union Station"
        assert label.startswith("Union Station, Washington")

    def test_a_town_is_not_named_twice(self) -> None:
        name, label = geocode.describe(
            {
                "type": "city",
                "name": "Purcellville",
                "city": "Purcellville",
                "county": "Loudoun County",
                "state": "Virginia",
            },
            reverse=False,
        )
        assert name == "Purcellville"
        assert label.count("Purcellville") == 1
        assert "Loudoun County" in label

    def test_a_place_with_no_name_is_named_by_its_area(self) -> None:
        name, _label = geocode.describe({"type": "district", "city": "Baltimore"}, reverse=True)
        assert name == "Baltimore"

    def test_the_label_is_short(self) -> None:
        _name, label = geocode.describe(
            {
                "type": "street",
                "name": "Main Street",
                "district": "Old Town",
                "locality": "Ward 1",
                "city": "Fairfax",
                "county": "Fairfax County",
                "state": "Virginia",
            },
            reverse=True,
        )
        assert label.count(",") <= 2

    def test_a_feature_that_is_not_a_point_is_skipped(self) -> None:
        bad = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": []},
            "properties": {"name": "x"},
        }
        broken = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": ["a", 1]},
            "properties": {"name": "y"},
        }
        assert geocode.results(answer(bad, broken, "junk"), reverse=False) == []


def test_both_are_in_the_openapi_schema(client) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert {"200", "400", "429", "502"} <= set(paths[SEARCH]["get"]["responses"])
    assert {"200", "400", "429", "502"} <= set(paths[REVERSE]["get"]["responses"])


# --- the transport ------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"{}"
    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        self.seen.append(self.path)
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def photon_server():
    started = []

    def start(status: int, body: bytes):
        handler = type("H", (_Handler,), {"status": status, "body": body, "seen": []})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}", handler.seen

    yield start
    for httpd in started:
        httpd.shutdown()


class TestTransport:
    def test_it_asks_photons_path_with_the_parameters_encoded(self, photon_server) -> None:
        url, seen = photon_server(200, json.dumps(answer()).encode())
        with override_settings(PHOTON_URL=url):
            assert geocode._get("/api", {"q": "a&b=c", "limit": 2}) == answer()
        (path,) = seen
        parsed = urllib.parse.urlsplit(path)
        assert parsed.path == "/api"
        assert urllib.parse.parse_qs(parsed.query) == {"q": ["a&b=c"], "limit": ["2"]}

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (500, b"oops"),
            (400, b'{"message": "bad"}'),
            (200, b"<html>"),
            (200, b'{"no": "features"}'),
            (200, b"[1, 2]"),
            (200, b'{"features": []' + b" " * (geocode.MAX_ANSWER_BYTES + 10) + b"}"),
            # A whole answer inside the limit and padding past it: only the
            # size check refuses it, since what was read parses.
            (200, b'{"features": []}' + b" " * (geocode.MAX_ANSWER_BYTES + 10)),
        ],
    )
    def test_anything_but_a_feature_list_is_unavailable(self, photon_server, status, body) -> None:
        url, _seen = photon_server(status, body)
        with override_settings(PHOTON_URL=url), pytest.raises(geocode.Unavailable):
            geocode._get("/api", {"q": "x"})

    def test_nobody_listening_is_unavailable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with override_settings(PHOTON_URL=f"http://127.0.0.1:{port}"):
            with pytest.raises(geocode.Unavailable):
                geocode._get("/api", {"q": "x"})

    def test_a_geocoder_that_hangs_is_unavailable_within_the_timeout(self) -> None:
        with socket.socket() as silent:
            silent.bind(("127.0.0.1", 0))
            silent.listen()
            port = silent.getsockname()[1]
            with override_settings(PHOTON_URL=f"http://127.0.0.1:{port}", PHOTON_TIMEOUT_S=0.3):
                with pytest.raises(geocode.Unavailable):
                    geocode._get("/api", {"q": "x"})
