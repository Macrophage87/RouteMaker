"""The GBFS client (core.gbfs): parsing against sampled feeds, and the 60-second cache.

The fixtures in tests/data/gbfs are a small sanitized sample of the operator's official
feeds (checked 2026-10-04: GBFS 1.1; no geofencing_zones feed; one pricing plan, the
e-bike single ride, with no out-of-dock fee). They are a test sample, not a dataset
(OWNER-DECISIONS 300): do not enlarge them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core import gbfs

DATA = Path(__file__).parent / "data" / "gbfs"
DISCOVERY = "https://gbfs.capitalbikeshare.com/gbfs/gbfs.json"


def doc(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


class FakeNetwork:
    """A fetch that serves the fixtures by URL, and counts what was asked."""

    def __init__(self, fail: set[str] | None = None, drop: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail or set()
        self.down = False
        self.drop = drop or set()
        self.discovery = doc("gbfs")
        for feed in self.discovery["data"]["en"]["feeds"]:
            self.by_url = getattr(self, "by_url", {})
            self.by_url[feed["url"]] = feed["name"]
        self.discovery["data"]["en"]["feeds"] = [
            f for f in self.discovery["data"]["en"]["feeds"] if f["name"] not in self.drop
        ]

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        assert timeout <= gbfs.TIMEOUT_S
        if self.down:
            raise gbfs.Unavailable("down")
        if url == DISCOVERY:
            return json.dumps(self.discovery).encode()
        name = self.by_url[url]
        if name in self.fail:
            raise gbfs.Unavailable(f"{name} failed")
        return (DATA / f"{name}.json").read_bytes()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- Discovery and what the operator publishes ----------------------------------------


def test_discovery_lists_the_feeds_and_publishes_no_geofencing_zones() -> None:
    feeds = gbfs.parse_discovery(doc("gbfs"))
    assert doc("gbfs")["version"] == "1.1"
    for name in (
        "station_information",
        "station_status",
        "free_bike_status",
        "system_pricing_plans",
    ):
        assert name in feeds
    assert "system_alerts" in feeds
    assert "geofencing_zones" not in feeds
    assert all(gbfs.allowed_url(url) for url in feeds.values())


def test_only_official_https_urls_are_followed() -> None:
    assert gbfs.allowed_url("https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/station_status.json")
    assert gbfs.allowed_url(DISCOVERY)
    assert not gbfs.allowed_url("http://gbfs.lyft.com/x.json")  # not https
    assert not gbfs.allowed_url("https://example.org/gbfs.json")
    assert not gbfs.allowed_url("https://gbfs.lyft.com@evil.example/x.json")
    assert not gbfs.allowed_url("https://user:pw@gbfs.lyft.com/x.json")
    assert not gbfs.allowed_url("https://gbfs.lyft.com.evil.example/x.json")
    hostile = {
        "data": {
            "en": {
                "feeds": [
                    {"name": "station_information", "url": "https://evil.example/si.json"},
                    {"name": "station_status", "url": "https://gbfs.lyft.com/ss.json"},
                ]
            }
        }
    }
    assert gbfs.parse_discovery(hostile) == {"station_status": "https://gbfs.lyft.com/ss.json"}


def test_a_request_carries_nothing_of_the_visitor(monkeypatch) -> None:
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, limit):
            return b"{}"

    def fake_open(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(gbfs._OPENER, "open", fake_open)
    gbfs.http_get(DISCOVERY, 3.0)
    request: urllib.request.Request = seen["request"]
    assert request.data is None  # no body
    assert request.get_method() == "GET"
    assert {k.lower() for k in request.headers} == {
        "accept",
        "user-agent",
    }  # no cookie, no forwarding
    assert request.get_header("User-agent") == gbfs.USER_AGENT
    assert seen["timeout"] == 3.0


def test_a_redirect_off_the_operators_hosts_is_refused() -> None:
    handler = gbfs._SameHostsOnly()
    request = urllib.request.Request(
        "https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/station_status.json"
    )
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://example.org/elsewhere.json"
        )
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://gbfs.lyft.com/plain.json")
    followed = handler.redirect_request(
        request, None, 302, "Found", {}, "https://gbfs.capitalbikeshare.com/gbfs/gbfs.json"
    )
    assert (
        followed is not None
        and followed.full_url == "https://gbfs.capitalbikeshare.com/gbfs/gbfs.json"
    )


def test_a_feed_larger_than_expected_is_refused(monkeypatch) -> None:
    class Big:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, limit):
            return b"x" * limit

    monkeypatch.setattr(gbfs._OPENER, "open", lambda request, timeout: Big())
    with pytest.raises(gbfs.Unavailable, match="larger than expected"):
        gbfs.http_get(DISCOVERY, 3.0)


def test_a_url_off_the_operators_hosts_is_never_requested() -> None:
    with pytest.raises(gbfs.Unavailable):
        gbfs.http_get("https://example.org/gbfs.json", 1.0)


# --- Parsing ------------------------------------------------------------------------


def test_stations_are_parsed_and_names_tidied() -> None:
    stations = gbfs.parse_stations(doc("station_information"))
    assert len(stations) == 27
    by_name = {s.name: s for s in stations}
    # The feed has "20th & M St NW " with a trailing space.
    assert "20th & M St NW" in by_name
    union = by_name["Columbus Circle / Union Station"]
    assert (union.lon, union.lat) == (-77.00493, 38.89696)
    assert union.capacity is not None and union.capacity >= 40


def test_malformed_stations_are_skipped() -> None:
    broken = {
        "data": {
            "stations": [
                {"station_id": "a", "name": "ok", "lon": -77.0, "lat": 38.9},
                {"station_id": "b", "name": "no coordinates"},
                {"station_id": "c", "name": "bad lat", "lon": -77.0, "lat": 123.0},
                {"station_id": "", "name": "no id", "lon": -77.0, "lat": 38.9},
                "not a dict",
                {"station_id": "d", "lon": True, "lat": 38.9},
            ]
        }
    }
    assert [s.station_id for s in gbfs.parse_stations(broken)] == ["a"]
    assert gbfs.parse_stations({}) == [] and gbfs.parse_stations({"data": []}) == []


def test_a_classic_bike_is_every_bike_that_is_not_an_ebike() -> None:
    status = gbfs.parse_status(doc("station_status"))
    stations = {s.name: s for s in gbfs.parse_stations(doc("station_information"))}
    # 17th St & Massachusetts Ave NW: 14 bikes, 2 of them e-bikes, 4 free slots.
    st = status[stations["17th St & Massachusetts Ave NW"].station_id]
    assert (st.bikes, st.ebikes, st.docks) == (14, 2, 4)
    assert st.classic == 12
    assert st.bikes_of("classic") == 12 and st.bikes_of("ebike") == 2
    assert st.can_rent and st.can_return
    # A station with no free slots cannot take a bike back.
    full = status[stations["22nd & P ST NW"].station_id]
    assert full.docks == 0 and not full.can_return and full.can_rent


def test_a_station_that_is_not_renting_cannot_start_a_ride() -> None:
    status = gbfs.parse_status(
        {
            "data": {
                "stations": [
                    {
                        "station_id": "a",
                        "num_bikes_available": 5,
                        "num_docks_available": 5,
                        "is_installed": 1,
                        "is_renting": 0,
                        "is_returning": 1,
                    }
                ]
            }
        }
    )
    assert not status["a"].can_rent and status["a"].can_return


def test_ebikes_cannot_exceed_bikes() -> None:
    status = gbfs.parse_status(
        {
            "data": {
                "stations": [
                    {"station_id": "a", "num_bikes_available": 1, "num_ebikes_available": 4}
                ]
            }
        }
    )
    assert status["a"].bikes_of("ebike") == 1 and status["a"].classic == 0


def test_free_bikes_keep_only_available_ebikes() -> None:
    found = gbfs.parse_free_bikes(doc("free_bike_status"))
    assert len(found) == 50
    mixed = {
        "data": {
            "bikes": [
                {"bike_id": "1", "lon": -77.0, "lat": 38.9, "type": "electric_bike"},
                {
                    "bike_id": "2",
                    "lon": -77.0,
                    "lat": 38.9,
                    "type": "electric_bike",
                    "is_reserved": 1,
                },
                {
                    "bike_id": "3",
                    "lon": -77.0,
                    "lat": 38.9,
                    "type": "electric_bike",
                    "is_disabled": 1,
                },
                {"bike_id": "4", "lon": -77.0, "lat": 38.9, "type": "scooter"},
                {"bike_id": "5", "lon": "x", "lat": 38.9, "type": "electric_bike"},
            ]
        }
    }
    assert [b.bike_id for b in gbfs.parse_free_bikes(mixed)] == ["1"]


def test_the_pricing_plan_is_read_and_it_names_no_out_of_dock_fee() -> None:
    plans = gbfs.parse_pricing(doc("system_pricing_plans"))
    assert [p.plan_id for p in plans] == ["EBIKE_SINGLE_RIDE"]
    assert plans[0].price == "1.00" and plans[0].currency == "USD"
    assert "per minute" in plans[0].description
    # The sampled plan is a ride's price, not a parking fee: nothing is invented.
    assert gbfs.out_of_dock_fee(plans) is None


@pytest.mark.parametrize(
    "text",
    [
        "Out-of-dock fee",
        "Fee for parking outside of a dock",
        "$2.00 non-dock parking",
        "E-bike left outside a station",
        "Free-floating parking surcharge",
    ],
)
def test_a_plan_that_names_an_out_of_dock_fee_is_found(text: str) -> None:
    plans = gbfs.parse_pricing(
        {
            "data": {
                "plans": [
                    {"plan_id": "RIDE", "name": "ride", "price": 1, "description": "ride"},
                    {"plan_id": "P2", "name": text, "price": "2.5", "currency": "USD"},
                ]
            }
        }
    )
    found = gbfs.out_of_dock_fee(plans)
    assert found is not None and found.plan_id == "P2" and found.price == "2.50"


def test_a_plan_with_an_unreadable_price_is_skipped() -> None:
    assert gbfs.parse_pricing({"data": {"plans": [{"plan_id": "x", "price": "free-ish"}]}}) == []


SQUARE = [[-77.02, 38.89], [-77.00, 38.89], [-77.00, 38.91], [-77.02, 38.91], [-77.02, 38.89]]
HOLE = [
    [-77.012, 38.898],
    [-77.008, 38.898],
    [-77.008, 38.902],
    [-77.012, 38.902],
    [-77.012, 38.898],
]


def zones_doc(rules, rings=None, global_rules=None) -> dict:
    return {
        "data": {
            "geofencing_zones": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": rings or [SQUARE]},
                        "properties": {"name": "zone", "rules": rules},
                    }
                ],
                **({"global_rules": global_rules} if global_rules else {}),
            }
        }
    }


def test_zones_bar_ending_where_ride_is_not_allowed() -> None:
    zones = gbfs.parse_zones(zones_doc([{"ride_allowed": False}]))
    assert zones is not None
    assert not zones.allows_ending(-77.010, 38.90)
    assert zones.allows_ending(-77.05, 38.90)  # outside the zone


def test_zones_bar_ending_where_station_parking_is_required() -> None:
    zones = gbfs.parse_zones(zones_doc([{"ride_allowed": True, "station_parking": True}]))
    assert zones is not None and not zones.allows_ending(-77.010, 38.90)


def test_a_zone_that_allows_riding_does_not_bar_ending() -> None:
    zones = gbfs.parse_zones(zones_doc([{"ride_allowed": True, "maximum_speed_kph": 10}]))
    assert zones is not None and zones.allows_ending(-77.010, 38.90)


def test_a_hole_in_a_zone_is_outside_it() -> None:
    zones = gbfs.parse_zones(zones_doc([{"ride_allowed": False}], rings=[SQUARE, HOLE]))
    assert zones is not None
    assert not zones.allows_ending(-77.018, 38.90)
    assert zones.allows_ending(-77.010, 38.90)


def test_a_global_rule_that_bars_ending_applies_everywhere() -> None:
    zones = gbfs.parse_zones(zones_doc([], global_rules=[{"ride_allowed": False}]))
    assert zones is not None and not zones.allows_ending(-77.5, 38.0)


def test_a_multipolygon_zone() -> None:
    far = [[[-76.0, 39.0], [-75.9, 39.0], [-75.9, 39.1], [-76.0, 39.1], [-76.0, 39.0]]]
    data = zones_doc([{"ride_allowed": False}])
    feature = data["data"]["geofencing_zones"]["features"][0]
    feature["geometry"] = {"type": "MultiPolygon", "coordinates": [[SQUARE], far]}
    zones = gbfs.parse_zones(data)
    assert zones is not None
    assert not zones.allows_ending(-77.010, 38.90) and not zones.allows_ending(-75.95, 39.05)


def test_a_document_that_is_not_zones_is_not_zones() -> None:
    assert gbfs.parse_zones({"data": {"stations": []}}) is None
    assert gbfs.parse_zones({}) is None


def test_alerts_are_the_operators_own_summaries() -> None:
    assert gbfs.parse_alerts(doc("system_alerts")) == []
    alerts = {
        "data": {"alerts": [{"summary": "  Docks closed\n on K St "}, {"description": "Other"}, {}]}
    }
    assert gbfs.parse_alerts(alerts) == ["Docks closed on K St", "Other"]


# --- The cache ------------------------------------------------------------------------


def test_a_snapshot_is_built_from_the_discovered_feeds() -> None:
    net = FakeNetwork()
    snap = gbfs.Gbfs(net, Clock()).snapshot()
    assert len(snap.stations) == 27
    assert snap.status is not None and snap.free_bikes is not None and snap.pricing is not None
    assert snap.alerts == []
    assert snap.zones is None and snap.unlisted == {"geofencing_zones"} and not snap.failed
    # Discovery first, then only the feeds the planner reads: nothing else is downloaded.
    assert net.calls[0] == DISCOVERY
    names = sorted(net.by_url[u] for u in net.calls[1:])
    assert names == [
        "free_bike_status",
        "station_information",
        "station_status",
        "system_alerts",
        "system_pricing_plans",
    ]


def test_the_snapshot_is_kept_about_sixty_seconds_and_then_fetched_again() -> None:
    net, clock = FakeNetwork(), Clock()
    cache = gbfs.Gbfs(net, clock)
    first = cache.snapshot()
    clock.now += gbfs.CACHE_TTL_S - 1
    assert cache.snapshot() is first
    assert cache.refreshes == 1 and len(net.calls) == 6
    clock.now += 2
    second = cache.snapshot()
    assert second is not first and cache.refreshes == 2 and len(net.calls) == 12
    assert gbfs.CACHE_TTL_S == 60.0


def test_a_failed_refresh_serves_the_last_snapshot_for_a_short_grace_only() -> None:
    net, clock = FakeNetwork(), Clock()
    cache = gbfs.Gbfs(net, clock)
    cache.snapshot()
    net.down = True
    clock.now += gbfs.CACHE_TTL_S + 1
    stale = cache.snapshot()
    assert stale.stale and len(stale.stations) == 27
    clock.now += gbfs.STALE_GRACE_S  # past the grace
    with pytest.raises(gbfs.Unavailable):
        cache.snapshot()


def test_a_failed_refresh_is_not_tried_again_at_once() -> None:
    net, clock = FakeNetwork(), Clock()
    net.down = True
    cache = gbfs.Gbfs(net, clock)
    with pytest.raises(gbfs.Unavailable):
        cache.snapshot()
    asked = len(net.calls)
    clock.now += 1
    with pytest.raises(gbfs.Unavailable):
        cache.snapshot()
    assert len(net.calls) == asked  # paused
    clock.now += gbfs.FAILURE_PAUSE_S
    net.down = False
    assert len(cache.snapshot().stations) == 27


def test_an_optional_feed_that_fails_is_unknown_not_empty() -> None:
    net = FakeNetwork(fail={"station_status", "free_bike_status"})
    snap = gbfs.Gbfs(net, Clock()).snapshot()
    assert snap.status is None and snap.free_bikes is None
    assert snap.failed == {"station_status", "free_bike_status"}
    assert snap.pricing is not None  # the rest is still read


def test_without_the_station_list_there_is_no_snapshot() -> None:
    cache = gbfs.Gbfs(FakeNetwork(fail={"station_information"}), Clock())
    with pytest.raises(gbfs.Unavailable):
        cache.snapshot()
    cache = gbfs.Gbfs(FakeNetwork(drop={"station_information"}), Clock())
    with pytest.raises(gbfs.Unavailable):
        cache.snapshot()


def test_a_feed_discovery_does_not_list_is_not_fetched() -> None:
    net = FakeNetwork(drop={"free_bike_status", "system_pricing_plans"})
    snap = gbfs.Gbfs(net, Clock()).snapshot()
    assert snap.free_bikes is None and snap.pricing is None
    assert {"free_bike_status", "system_pricing_plans", "geofencing_zones"} <= snap.unlisted
    assert not any(net.by_url[u] == "free_bike_status" for u in net.calls[1:])


def test_garbage_from_a_feed_is_a_failed_feed() -> None:
    class Garbage(FakeNetwork):
        def __call__(self, url, timeout):
            if self.by_url.get(url) == "station_status":
                return b"<html>not json</html>"
            return super().__call__(url, timeout)

    snap = gbfs.Gbfs(Garbage(), Clock()).snapshot()
    assert snap.status is None and "station_status" in snap.failed


def test_geofencing_zones_are_read_where_the_operator_publishes_them() -> None:
    zones = zones_doc([{"ride_allowed": False}])

    class WithZones(FakeNetwork):
        def __init__(self):
            super().__init__()
            self.discovery["data"]["en"]["feeds"].append(
                {
                    "name": "geofencing_zones",
                    "url": "https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/geofencing_zones.json",
                }
            )
            self.by_url["https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/geofencing_zones.json"] = (
                "geofencing_zones"
            )

        def __call__(self, url, timeout):
            if self.by_url.get(url) == "geofencing_zones":
                self.calls.append(url)
                return json.dumps(zones).encode()
            return super().__call__(url, timeout)

    snap = gbfs.Gbfs(WithZones(), Clock()).snapshot()
    assert snap.zones is not None and "geofencing_zones" not in snap.unlisted
    assert not snap.zones.allows_ending(-77.010, 38.90)


def test_nothing_is_written_anywhere() -> None:
    """The cache is in memory only: the module has no file, database or export."""
    source = (Path(gbfs.__file__)).read_text()
    for forbidden in (
        "open(",
        "write_text",
        "write_bytes",
        "sqlite",
        "connection",
        "pickle",
        "shelve",
        "cache.set",
    ):
        assert forbidden not in source.replace("_OPENER.open(", ""), forbidden


def test_a_dock_out_of_service_takes_and_gives_no_bikes() -> None:
    status = gbfs.parse_status(
        {
            "data": {
                "stations": [
                    {
                        "station_id": "a",
                        "num_bikes_available": 5,
                        "num_docks_available": 5,
                        "is_installed": 0,
                        "is_renting": 1,
                        "is_returning": 1,
                    }
                ]
            }
        }
    )
    assert not status["a"].can_rent and not status["a"].can_return


def test_a_listed_feed_that_is_not_zones_is_a_failed_feed_not_an_empty_one() -> None:
    class NotZones(FakeNetwork):
        def __init__(self):
            super().__init__()
            url = "https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/geofencing_zones.json"
            self.discovery["data"]["en"]["feeds"].append({"name": "geofencing_zones", "url": url})
            self.by_url[url] = "geofencing_zones"

        def __call__(self, url, timeout):
            if self.by_url.get(url) == "geofencing_zones":
                self.calls.append(url)
                return b'{"data": {"stations": []}}'
            return super().__call__(url, timeout)

    snap = gbfs.Gbfs(NotZones(), Clock()).snapshot()
    assert snap.zones is None and "geofencing_zones" in snap.failed
