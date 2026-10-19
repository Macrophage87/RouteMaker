"""DC's closures fetched, placed, kept and used (core.closure_sources; v0.7.0 "DC closures
source", "Closures on the map"). The network and the placing are fakes; the database is real."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core import closure_sources as sources
from core import workzones
from core.models import BikeshareFeedCache
from routemaker import workzones as wz

db = pytest.mark.django_db(transaction=True)
DATA = Path(__file__).resolve().parent / "data" / "closures"
# The day of the sample AlertDC feed; the MPD sample is for an event on Sep 7.
NOW = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
KEY = "not-a-real-nps-key-0123"
# The made-up event at the MPD sample's own hours, but a week ahead of NOW.
ADVISORY = (
    (DATA / "mpd-traffic-advisory.html")
    .read_text()
    .replace("September 7, 2026", "October 19, 2026")
    .replace("September 8, 2026", "October 20, 2026")
)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(sources.NPS_KEY_ENV, raising=False)
    workzones.forget()
    yield
    workzones.forget()


class Net:
    """Answers by host, recording each URL and its headers."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.asked: list[tuple[str, dict]] = []
        self.fail = fail

    def __call__(self, url: str, timeout: float, headers: dict) -> bytes:
        self.asked.append((url, headers))
        if any(f in url for f in self.fail):
            raise workzones.FeedError("HTTP 503")
        if "maps2.dcgis.dc.gov" in url:
            return (DATA / "tops-permits.geojson").read_bytes()
        if url == sources.URLS["mpd"]:
            return (DATA / "mpd-newsroom.html").read_bytes()
        if "labor-day" in url:
            return ADVISORY.encode()
        if "mpdc.dc.gov/release" in url:
            raise workzones.FeedError("HTTP 404")
        if "hsema" in url:
            return (DATA / "alertdc-nrss.xml").read_bytes()
        if "developer.nps.gov" in url:
            return (DATA / "nps-alerts.json").read_bytes()
        raise AssertionError(url)


class Placer:
    """Places every permit on a short east-west block at its point, and every segment
    but Constitution Avenue's on a line; counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def permit_line(self, point):
        self.calls += 1
        return [(point[0] - 0.0005, point[1]), (point[0] + 0.0005, point[1])]

    def segment_line(self, segment):
        self.calls += 1
        if segment.street.startswith("Constitution"):
            return None
        return [(-77.035, 38.888), (-77.040, 38.888)]


def no_sleep(_s: float) -> None:
    pass


def stored(source: str) -> dict:
    return BikeshareFeedCache.objects.get(key=sources.KEY).payload["feeds"][source]


@db
class TestRefresh:
    def test_the_public_sources_are_read_and_nps_not_without_the_key(self) -> None:
        net = Net()
        line = sources.refresh(net, no_sleep, lambda: NOW, Placer())
        assert line.startswith("closures: dc 2 closures, 0 notices, mpd ")
        assert not any("nps.gov" in url for url, _h in net.asked)
        assert {z["id"] for z in stored("dc")["zones"]} == {"dc-PA261001", "dc-PA261002"}
        mpd = stored("mpd")
        assert sorted(z["road"] for z in mpd["zones"]) == [
            "15th Street NW",
            "17th Street NW",
            "Jefferson Drive SW",
            "Madison Drive NW",
        ]
        # Constitution Avenue could not be placed and Independence Avenue would not parse:
        # both are text under "Check before you go", with the link.
        (notice,) = mpd["notices"]
        assert "Constitution Avenue" in notice["text"] and "Independence Avenue" in notice["text"]
        assert notice["url"].startswith("https://mpdc.dc.gov/release/")

    def test_crime_and_other_alerts_are_never_stored(self) -> None:
        sources.refresh(Net(), no_sleep, lambda: NOW, Placer())
        kept = json.dumps(BikeshareFeedCache.objects.get(key=sources.KEY).payload)
        for word in ("shooting", "Police Activity", "police activity", "Wind Advisory", "Arrest"):
            assert word not in kept

    def test_nps_with_the_key_in_its_header_never_in_a_url_or_the_log(
        self, monkeypatch, caplog
    ) -> None:
        monkeypatch.setenv(sources.NPS_KEY_ENV, KEY)
        net = Net(fail=("developer.nps.gov",))
        sources.refresh(net, no_sleep, lambda: NOW, Placer())
        nps = [(url, h) for url, h in net.asked if "developer.nps.gov" in url]
        assert len(nps) == sources.TRIES
        assert all(h["X-Api-Key"] == KEY and KEY not in url for url, h in nps)
        assert "parkCode=rocr%2Cnama%2Cgwmp%2Cchoh%2Canac" in nps[0][0]
        assert KEY not in caplog.text
        sources.refresh(Net(), no_sleep, lambda: NOW + timedelta(hours=1), Placer())
        assert [n["area"] for n in stored("nps")["notices"]] == ["rocr", "gwmp"]

    def test_each_source_is_read_when_due_and_places_are_remembered(self) -> None:
        placer = Placer()
        sources.refresh(Net(), no_sleep, lambda: NOW, placer)
        first = placer.calls
        net = Net()
        assert sources.refresh(net, no_sleep, lambda: NOW + timedelta(minutes=5), placer) == (
            "closures: nothing due"
        )
        assert net.asked == []
        later = NOW + timedelta(minutes=16)
        sources.refresh(net, no_sleep, lambda: later, placer)
        assert not any("maps2" in url for url, _h in net.asked), "the permits are hourly"
        # Constitution Avenue was not placed: it is looked for again only after RETRY_PLACE_S.
        assert placer.calls == first

    def test_nothing_starts_past_the_refresh_budget(self) -> None:
        """Every 15 minutes on a maintenance slot: past `REFRESH_BUDGET_S` no fetch, retry or
        place look-up starts, a fetch is cut to what is left, and a source not reached keeps
        its last good copy and is due again next time."""
        sources.refresh(Net(), no_sleep, lambda: NOW, Placer())
        assert sources.REFRESH_BUDGET_S <= 5 * 60

        clock = [0.0]
        timeouts: list[float] = []

        class Slow(Net):
            def __call__(self, url, timeout, headers):
                timeouts.append(timeout)
                clock[0] += 70.0  # each fetch takes 70 s of the budget
                return super().__call__(url, timeout, headers)

        placer = Placer()
        later = NOW + timedelta(hours=2)
        net = Slow()
        line = sources.refresh(
            net, no_sleep, lambda: later, placer, budget_s=100.0, clock=lambda: clock[0]
        )
        assert "not reached in time" in line
        assert all(t <= sources.TIMEOUT_S for t in timeouts) and timeouts[1] <= 30.0
        assert clock[0] <= 100.0 + 70.0, "nothing was started past the budget"
        # A source not reached keeps its copy from the first refresh, unfailed.
        alertdc = stored("alertdc")
        assert alertdc["read_at"] == NOW.isoformat() and alertdc["failed_at"] is None
        # A source cut short mid-fetch is not failed either, so it is due at the next tick.
        assert all(stored(source)["failed_at"] is None for source in ("dc", "mpd", "alertdc"))

    def test_a_failed_source_keeps_its_last_good_copy(self) -> None:
        sources.refresh(Net(), no_sleep, lambda: NOW, Placer())
        later = NOW + timedelta(hours=2)
        sources.refresh(Net(fail=("maps2",)), no_sleep, lambda: later, Placer())
        dc = stored("dc")
        assert dc["failed_at"] == later.isoformat() and len(dc["zones"]) == 2


@db
def test_the_snapshot_holds_the_work_zones_and_the_dc_closures_side_by_side(monkeypatch) -> None:
    monkeypatch.setattr(workzones, "_now", lambda: NOW)
    sources.refresh(Net(), no_sleep, lambda: NOW, Placer())
    found = workzones.snapshot()
    assert found.status == {"alertdc": "current", "dc": "current", "mpd": "current"}
    assert {z.source for z in found.zones} == {"dc", "mpd", "alertdc"}
    assert {n.source for n in found.notices} == {"mpd", "alertdc"}
    workzones.forget()
    status = sources.load(
        BikeshareFeedCache.objects.get(key=sources.KEY).payload, NOW + timedelta(hours=7)
    )[2]
    assert status == {"alertdc": "unavailable", "dc": "stale", "mpd": "unavailable"}


# --- The closure check (the dialog's POST /api/closures/check), fed by the DC sources --

LINE = [[-77.0400 + i * 0.002, 38.9000] for i in range(11)]
ALONG = tuple((-77.0350 + i * 0.001, 38.9000) for i in range(6))


def zone(zone_id, source="mpd", kind=wz.CLOSED, start=None, end=None):
    return wz.Zone(
        zone_id, source, kind, 0, ALONG, "K Street NW", None, start, end,
        title="K Street NW closed, 14th Street to 12th Street",
        url="https://mpdc.dc.gov/node/1",
        published=NOW - timedelta(days=1),
    )  # fmt: skip


@pytest.fixture
def snap(monkeypatch):
    def use(*zones, notices=()):
        status = {"mpd": workzones.CURRENT, "dc": workzones.CURRENT}
        found = workzones.Snapshot(tuple(zones), status, {}, tuple(notices))
        monkeypatch.setattr(workzones, "snapshot", lambda now=None: found)

    return use


def test_the_check_sees_dc_closures_at_the_ride_time_not_today(snap) -> None:
    today = zone("mpd-1", start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=3))
    snap(today)
    found = workzones.closures_on(LINE, now=NOW, when="weekend")
    assert found["closures"] == [], "a Saturday ride does not meet today's closure"
    found = workzones.closures_on(LINE, at=NOW, now=NOW)
    (c,) = found["closures"]
    assert c["source"] == "MPD traffic advisory" and c["source_key"] == "mpd"
    assert c["url"] == "https://mpdc.dc.gov/node/1"
    assert c["title"].startswith("K Street NW closed") and c["when_text"].startswith("Closed today")


def test_the_check_says_may_still_apply_leaves_out_a_bypass_and_lists_lanes(snap) -> None:
    lane = zone("dc-2", source="dc", kind=wz.LANE, end=NOW + timedelta(days=3))
    snap(zone("mpd-1"), zone("mpd-2", end=NOW + timedelta(days=9)), lane)
    saturday = NOW + timedelta(days=2)
    found = workzones.closures_on(LINE, at=saturday, now=NOW, bypass=["mpd-2"])
    (c,) = found["closures"]
    assert c["id"] == "mpd-1" and c["may_still_apply"]
    assert "may still apply on your ride day" in c["text"]
    assert [b["id"] for b in found["bypassed"]] == ["mpd-2"]
    assert [x["id"] for x in found["lanes"]] == ["dc-2"]


def test_the_check_has_the_park_notices_of_a_line_through_the_park(snap) -> None:
    from routemaker import dc_closures as dc

    park = dc.Notice("nps-1", "nps", "Beach Drive closed", "Repairs.", None, "rocr")
    snap(notices=(park,))
    through = [[-77.05, 38.93], [-77.05, 38.95]]
    (n,) = workzones.closures_on(through, at=NOW, now=NOW)["notices"]
    assert n["area_name"] == "Rock Creek Park" and n["point"] == [-77.0525, 38.9406]
    assert n["url"] == "https://www.nps.gov/rocr/planyourvisit/conditions.htm"
    assert workzones.closures_on(LINE, at=NOW, now=NOW)["notices"] == []


@pytest.mark.django_db
def test_the_endpoint_takes_when_and_bypass(client, snap) -> None:
    snap(zone("mpd-1", end=NOW + timedelta(days=400)), zone("mpd-2", end=NOW + timedelta(days=400)))
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.12"}

    def post(body):
        return client.post(
            "/api/closures/check", data=json.dumps(body), content_type="application/json", **headers
        )

    r = post({"line": LINE, "when": "weekend", "bypass": ["mpd-2"]})
    assert r.status_code == 200, r.content
    assert [c["id"] for c in r.json()["closures"]] == ["mpd-1"]
    assert post({"line": LINE, "when": "someday"}).status_code == 400
    assert post({"line": LINE, "bypass": "mpd-1"}).status_code == 400


def test_go_and_a_ride_leave_out_ddots_permits_plan_keeps_them(snap) -> None:
    # The owner, 2026-10-19: permits are roads that "could potentially be closed in the near
    # future", not useful on the go, "worth keeping for future ride planning".
    permit = zone("dc-1", source="dc", end=NOW + timedelta(days=30))
    lane = zone("dc-2", source="dc", kind=wz.LANE, end=NOW + timedelta(days=30))
    snap(permit, lane, zone("mpd-1", end=NOW + timedelta(hours=3)))
    planned = workzones.closures_on(LINE, at=NOW, now=NOW)
    assert [c["id"] for c in planned["closures"]] == ["dc-1", "mpd-1"]
    assert [x["id"] for x in planned["lanes"]] == ["dc-2"]
    now = workzones.closures_on(LINE, at=NOW, now=NOW, now_only=True)
    assert [c["id"] for c in now["closures"]] == ["mpd-1"]
    assert now["lanes"] == []
    plan = wz.for_plan([permit, lane], NOW, [LINE[0], LINE[-1]], {}, now=NOW)
    assert [z.zone_id for z in plan.excluded] == ["dc-1"] and plan.lanes == [lane]
    go = wz.for_plan([permit, lane], NOW, [LINE[0], LINE[-1]], {}, now=NOW, now_only=True)
    assert go.excluded == [] and go.exclude == [] and go.lanes == []


@pytest.mark.django_db
def test_the_endpoint_takes_now_only(client, snap) -> None:
    snap(zone("dc-1", source="dc", end=NOW + timedelta(days=400)))
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.13"}

    def post(body):
        return client.post(
            "/api/closures/check", data=json.dumps(body), content_type="application/json", **headers
        )

    line = {"line": LINE}
    assert [c["id"] for c in post(line).json()["closures"]] == ["dc-1"]
    assert post({**line, "now_only": True}).json()["closures"] == []
    assert post({**line, "now_only": "yes"}).status_code == 400


# --- The route's map: its closures, their effect and delay -----------------------------


def test_measure_delays_names_the_closure_that_changed_the_route_and_its_detour() -> None:
    closed = zone("mpd-1", end=NOW + timedelta(days=1))
    plan = wz.for_plan([closed], NOW, [LINE[0], LINE[-1]], {}, now=NOW)
    assert plan.excluded and plan.exclude
    request = {"locations": [], "exclude_polygons": list(plan.exclude)}
    from test_route_api import encode_polyline6

    def answer(line, seconds):
        shape = encode_polyline6([tuple(p) for p in line])
        return {"trip": {"legs": [{"shape": shape}], "summary": {"time": seconds}}}

    straight = answer(LINE, 300.0)
    detour = answer([LINE[0], [-77.03, 38.905], LINE[-1]], 540.0)
    asked = []

    def reroute(trial):
        asked.append(trial)
        return straight

    workzones.measure_delays(detour, request, plan, reroute, lambda: 30.0)
    assert "exclude_polygons" not in asked[0], "asked once without the closure"
    assert plan.affecting == {"mpd-1"} and plan.delays == {"mpd-1": 240.0}
    detour_line = [LINE[0], [-77.03, 38.905], LINE[-1]]
    rows = workzones.map_rows(detour_line, plan, [], 1.0, NOW)
    (row,) = rows
    assert row["effect"] == "routed_round" and row["effect_text"] == "Detour adds about 4 min"
    assert row["can_bypass"] and row["severity"] == "red"


def test_a_closure_off_the_route_has_no_effect_and_a_bypassed_one_a_small_marker() -> None:
    far = wz.Zone(
        "dc-9", "dc", wz.CLOSED, 0, ((-77.03, 38.9025), (-77.028, 38.9025)), None, None, None, None
    )
    through = zone("mpd-1", end=NOW + timedelta(days=1))
    plan = wz.for_plan([far, through], NOW, [LINE[0], LINE[-1]], {}, now=NOW, bypass=["mpd-1"])
    body = {"geometry": {"coordinates": LINE}, "distance_m": 1700.0, "description": []}
    workzones.with_work_zones(body, plan, now=NOW)
    rows = {r["id"]: r for r in body["work_zones"]["closures"]}
    assert rows["mpd-1"]["effect"] == "bypassed" and rows["mpd-1"]["bypassed"]
    assert rows["dc-9"]["effect_text"] == "No effect on your route"
    assert body["work_zones"]["on_route"][0]["bypassed"]
    assert any(
        "You chose to route through it" in (e.get("citation") or "") for e in body["description"]
    )


# --- Placing on the live segment table ---------------------------------------------------

# K Street running east as one way (1), crossed by two streets (2, 3) 100 m apart.
WAYS = [
    (1, [(-77.0320, 38.9000), (-77.0310, 38.9000), (-77.0298, 38.9000), (-77.0280, 38.9000)]),
    (2, [(-77.0310, 38.8990), (-77.0310, 38.9000), (-77.0310, 38.9010)]),
    (3, [(-77.0298, 38.8990), (-77.0298, 38.9000), (-77.0298, 38.9010)]),
]


@pytest.fixture
def ways(segment_schemas):
    from django.db import connection

    live, _staging = segment_schemas
    with connection.cursor() as cursor:
        for way, line in WAYS:
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (%s, 0, ST_GeomFromText(%s, 4326), 2, 'test')",
                [way, wkt],
            )
    return live


@db
def test_a_permit_closes_the_block_its_point_is_snapped_to(ways) -> None:
    placer = sources.DatabasePlacer(ways)
    block = placer.permit_line((-77.0305, 38.90005))
    assert block[0][0] == pytest.approx(-77.0310, abs=1e-6)
    assert block[-1][0] == pytest.approx(-77.0298, abs=1e-6)
    assert placer.permit_line((-77.0, 38.95)) is None, "nothing within 30 m"


@db
def test_a_segment_is_placed_between_its_cross_streets_on_the_routers_check(
    ways, monkeypatch
) -> None:
    from test_route_api import encode_polyline6

    from core import geocode, routing
    from routemaker import dc_closures as dc

    names = {"K Street NW": 1, "13th Street NW": 2, "12th Street NW": 3}

    def photon(path, params):
        name = params["q"].split(",")[0]
        found = names.get(name)
        if not found:
            return {"features": []}
        properties = {"osm_type": "W", "osm_id": found, "name": name.replace(" NW", " Northwest")}
        point = list(WAYS[found - 1][1][0])
        return {"features": [{"geometry": {"coordinates": point}, "properties": properties}]}

    streets = {"value": ["K Street Northwest"]}

    def router(url, payload, timeout):
        a, b = payload["locations"]
        shape = encode_polyline6([(a["lon"], a["lat"]), (b["lon"], b["lat"])])
        maneuvers = [{"type": 1, "street_names": streets["value"]}, {"type": 4}]
        return {"trip": {"legs": [{"shape": shape, "maneuvers": maneuvers}]}}

    monkeypatch.setattr(geocode, "_get", photon)
    monkeypatch.setattr(routing, "_transport", router)
    segment = dc.Segment("K Street NW", "13th Street NW", "12th Street NW", NOW, None, "")
    line = sources.DatabasePlacer(ways).segment_line(segment)
    assert line is not None
    xs = sorted(p[0] for p in line)
    assert xs[0] == pytest.approx(-77.0310, abs=1e-5)
    assert xs[-1] == pytest.approx(-77.0298, abs=1e-5)
    # Where the router's way leaves K Street, nothing is guessed.
    streets["value"] = ["L Street Northwest"]
    assert sources.DatabasePlacer(ways).segment_line(segment) is None
