"""Work zones a feed gives only by their ends, put on the road between them (core.workzones.place,
routemaker.workzones.road_fits). The owner, 2026-10-25, of a Maryland zone on Georgia Ave from
Wheaton to Silver Spring drawn as one straight line: "This should follow the road, not be a
straight line". The router is a fake."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from test_route_api import encode_polyline6

from core import routing, workzones
from core.models import BikeshareFeedCache
from routemaker import workzones as wz

NOW = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
db = pytest.mark.django_db(transaction=True)

# A road that bends east of the straight line between its ends (about 4.5 km end to end, the
# bend about 400 m off it), as Georgia Ave does between Wheaton and Silver Spring.
A, B = (-77.050, 38.990), (-77.030, 38.950)
ROAD = [A, (-77.046, 38.980), (-77.040, 38.970), (-77.033, 38.960), B]


def zone(line=(A, B), roads=("MD 97",), kind=wz.PENALTY, from_ends=True) -> wz.Zone:
    return wz.Zone(
        "md-georgia",
        "md",
        kind,
        wz.LANE_PENALTY_S,
        tuple(line),
        "MD 97 southbound",
        None,
        None,
        None,
        roads=tuple(roads),
        from_ends=from_ends,
    )


def answer(shape, names=("MD 97", "Georgia Avenue"), length_m=None) -> dict:
    length_km = (length_m if length_m is not None else wz.line_m(shape)) / 1000
    return {
        "trip": {
            "legs": [
                {
                    "shape": encode_polyline6(shape),
                    "summary": {"length": length_km},
                    "maneuvers": [
                        {"type": 1, "length": length_km, "street_names": list(names)},
                        {"type": 4, "length": 0.0},
                    ],
                }
            ]
        }
    }


class TestRules:
    def test_only_long_gaps_are_routed(self) -> None:
        assert wz.gaps([A, B]) == [0]
        dense = [(-77.0, 38.9), (-77.0, 38.9005), (-77.0, 38.901)]  # 55 m apart
        assert wz.gaps(dense) == []

    def test_the_feeds_road_names_match_the_maps(self) -> None:
        assert wz.road_named("MD 97", ["MD-97"])
        assert wz.road_named("MD 97", ["Maryland Route 97"])
        assert wz.road_named("Georgia Avenue", ["GEORGIA AVE"])
        assert not wz.road_named("MD 390", ["MD 97"])
        assert not wz.road_named("Georgia Avenue", [])

    def test_a_way_much_longer_than_the_line_or_on_other_roads_is_not_the_road(self) -> None:
        assert wz.road_fits(4500, 4900, 4900, True)
        assert not wz.road_fits(4500, 6500, 6500, True)  # a detour, not the road
        assert not wz.road_fits(4500, 4900, 1000, True)  # mostly another road
        assert wz.road_fits(4500, 4900, 0, False)  # no names to go by: the length alone

    def test_pieces_stand_in_for_the_gaps(self) -> None:
        assert wz.join_pieces([A, B], {0: ROAD}) == tuple(ROAD)
        near = (B[0], B[1] - 0.0003)  # a short step past B, not a gap
        assert wz.join_pieces([A, B, near], {0: ROAD}) == (*ROAD, near)

    def test_roads_and_approximate_survive_the_stored_copy(self) -> None:
        z = zone()
        again = wz.Zone.from_json(json.loads(json.dumps({**z.to_json(), "approximate": True})))
        assert again.roads == ("MD 97",) and again.approximate
        assert not wz.Zone.from_json({k: v for k, v in z.to_json().items() if k != "roads"}).roads

    def test_parse_keeps_the_road_names(self) -> None:
        feature = {
            "id": "x",
            "properties": {"core_details": {"road_names": ["MD 97"]}, "vehicle_impact": "x"},
            "geometry": {"type": "MultiPoint", "coordinates": [list(A), list(B)]},
        }
        parsed = wz.parse_feature(feature, "md")
        assert parsed.roads == ("MD 97",) and parsed.from_ends
        feature["geometry"] = {"type": "LineString", "coordinates": [list(p) for p in ROAD]}
        assert not wz.parse_feature(feature, "md").from_ends

    def test_a_placed_road_is_thinned(self) -> None:
        dense = [(A[0], A[1] - i * 0.0001) for i in range(200)]  # a straight 2.2 km, every 11 m
        assert wz.simplify_m(dense, 4.0) == [list(dense[0]), list(dense[-1])]
        assert wz.simplify_m(ROAD, 4.0) == [list(p) for p in ROAD]

    def test_interstates_by_name(self) -> None:
        for name in ("I-97", "I 495", "Interstate 95", "IS 270", "I\u201197", "I-97A", "I-95 NB"):
            assert wz.on_interstate(zone(roads=(name,))), name
        for name in ("MD 97", "Ingleside Rd", "US 29", "Indian Head Hwy", "I-70 Business"):
            assert not wz.on_interstate(zone(roads=(name,))), name
        # Named for a road bikes may use as well: the work may be on it.
        assert not wz.on_interstate(zone(roads=("MD 32", "I-95")))
        assert not wz.on_interstate(zone(roads=()))

    def test_samples_spread_along_the_line(self) -> None:
        points = wz.samples(ROAD, 5)
        assert len(points) == 5
        assert len(wz.samples(ROAD, 1)) == 2
        assert points[0] == pytest.approx(A) and points[-1] == pytest.approx(B)


class TestRouting:
    def test_a_route_along_the_road_meets_the_placed_zone_not_the_straight_line(self) -> None:
        # The straight line is up to 400 m off the road, so a ride along the road missed its
        # heads-up and penalty; on the road, the route runs along it.
        assert wz.along(ROAD, [zone()]) == []
        placed = zone(line=ROAD)
        assert [p.zone.zone_id for p in wz.along(ROAD, [placed])] == ["md-georgia"]


class TestRoadLine:
    def ask(self, monkeypatch, answers):
        asked = []

        def transport(url, payload, timeout):
            asked.append(payload["locations"])
            reply = answers.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(routing, "_transport", transport)
        return asked

    def test_the_road_named_by_the_feed(self, monkeypatch) -> None:
        self.ask(monkeypatch, [answer(ROAD)])
        line = workzones.road_line(A, B, ("MD 97",))
        assert [tuple(p) for p in line] == ROAD

    def test_the_routers_shape_is_thinned(self, monkeypatch) -> None:
        # The router's shape every few metres along the same bends: thinned back to the bends.
        dense = []
        for (x0, y0), (x1, y1) in zip(ROAD, ROAD[1:], strict=False):
            dense += [(x0 + (x1 - x0) * k / 50, y0 + (y1 - y0) * k / 50) for k in range(50)]
        dense.append(B)
        self.ask(monkeypatch, [answer(dense)])
        line = workzones.road_line(A, B, ("MD 97",))
        assert [tuple(p) for p in line] == pytest.approx(ROAD)

    def test_a_one_way_road_is_asked_the_other_way_and_turned_round(self, monkeypatch) -> None:
        asked = self.ask(
            monkeypatch, [routing.RouterRefused(400, 442, "no path"), answer(ROAD[::-1])]
        )
        line = workzones.road_line(A, B, ("MD 97",))
        assert [tuple(p) for p in line] == ROAD
        assert asked[1][0] == {"lon": B[0], "lat": B[1]}

    def test_another_road_or_a_detour_is_not_taken(self, monkeypatch) -> None:
        self.ask(monkeypatch, [answer(ROAD, names=("MD 390",))] * 2)
        assert workzones.road_line(A, B, ("MD 97",)) is None
        self.ask(monkeypatch, [answer(ROAD, length_m=9000)] * 2)
        assert workzones.road_line(A, B, ("MD 97",)) is None

    def test_the_router_down_is_said_not_taken_for_no_road(self, monkeypatch) -> None:
        self.ask(monkeypatch, [routing.RouterUnavailable("down")] * 2)
        with pytest.raises(routing.RouterUnavailable):
            workzones.road_line(A, B, ("MD 97",))


class TestPlace:
    def test_a_zone_given_by_its_ends_is_put_on_the_road_once(self) -> None:
        calls = []

        def find(a, b, roads):
            calls.append((a, b, roads))
            return [list(p) for p in ROAD]

        [placed], kept = workzones.place([zone()], None, NOW, find=find)
        assert placed.line == tuple(ROAD) and not placed.approximate
        assert calls == [(A, B, ("MD 97",))]
        # The next refresh reuses the place, asking the router nothing.
        [again], _ = workzones.place([zone()], kept, NOW + timedelta(minutes=5), find=find)
        assert again.line == tuple(ROAD) and len(calls) == 1

    def test_a_long_line_not_found_on_the_road_is_not_drawn(self) -> None:
        [placed], kept = workzones.place([zone()], None, NOW, find=lambda a, b, r: None)
        assert placed.line == (A, B) and placed.approximate
        row = workzones.closure_row(placed, wz.NO_EFFECT, None, NOW, False)
        assert row["line"] == [] and row["point"] == [A[0], A[1]]
        # Looked for again only after a while.
        assert list(kept.values())[0]["line"] is None

    def test_a_short_one_not_found_is_drawn_as_given(self) -> None:
        short = ((-77.0, 38.9), (-77.0, 38.9025))  # about 280 m
        [placed], _ = workzones.place([zone(line=short)], None, NOW, find=lambda a, b, r: None)
        assert placed.line == short and not placed.approximate
        assert workzones.closure_row(placed, wz.NO_EFFECT, None, NOW, False)["line"]

    def test_a_dense_line_is_left_alone(self) -> None:
        dense = zone(line=ROAD[:1] + [(A[0], A[1] - 0.0005)])
        [placed], kept = workzones.place([dense], None, NOW, find=lambda a, b, r: 1 / 0)
        assert placed is dense and kept == {}

    def test_a_line_the_feed_drew_is_left_as_drawn(self) -> None:
        drawn = zone(from_ends=False)  # a LineString of its own, however sparse
        [placed], kept = workzones.place([drawn], None, NOW, find=lambda a, b, r: 1 / 0)
        assert placed is drawn and not placed.approximate and kept == {}

    def test_the_router_down_stops_the_lookups_and_remembers_nothing(self) -> None:
        calls = []

        def find(a, b, roads):
            calls.append(a)
            raise routing.RouterUnavailable("down")

        others = [zone(line=((A[0] + d, A[1]), (B[0] + d, B[1]))) for d in (0.1, 0.2)]
        placed, kept = workzones.place([zone(), *others], None, NOW, find=find)
        assert len(calls) == 2 and kept == {}  # two failures in a row stop it
        assert all(z.approximate for z in placed)

    def test_one_router_failure_does_not_stop_the_rest(self) -> None:
        answers = [routing.RouterUnavailable("timeout"), [list(p) for p in ROAD]]

        def find(a, b, roads):
            reply = answers.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        other = zone(line=((A[0] + 0.1, A[1]), (B[0] + 0.1, B[1])))
        [first, second], kept = workzones.place([zone(), other], None, NOW, find=find)
        assert first.approximate and second.line == tuple(ROAD) and len(kept) == 1

    def test_past_the_budget_nothing_is_asked_or_remembered(self) -> None:
        [placed], kept = workzones.place(
            [zone()], None, NOW, out_of_time=lambda: True, find=lambda a, b, r: 1 / 0
        )
        assert placed.approximate and kept == {}


@db
class TestBarred:
    SCHEMA = "barred_wz_test"

    @pytest.fixture
    def table(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE")
            cursor.execute(f"CREATE SCHEMA {self.SCHEMA}")
            cursor.execute(
                f"CREATE TABLE {self.SCHEMA}.segment "
                "(map_class text NOT NULL, geometry geometry(LineString, 4326) NOT NULL)"
            )
            # The motorway along the road; a street crossing it, open to bicycles.
            cursor.execute(
                f"INSERT INTO {self.SCHEMA}.segment VALUES "
                "('barred', ST_GeomFromText(%s, 4326)), ('road', ST_GeomFromText(%s, 4326))",
                [
                    "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in ROAD) + ")",
                    "LINESTRING(-77.06 38.97, -77.02 38.97)",
                ],
            )
        yield self.SCHEMA
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA {self.SCHEMA} CASCADE")

    def test_a_zone_along_a_barred_road_is_not_for_bikes(self, table) -> None:
        frontage = [(x + 0.0001, y) for x, y in ROAD]  # about 9 m beside the motorway
        zones = [
            zone(line=ROAD),
            zone(line=(A, B)),  # the straight line only meets it at its ends
            zone(line=((-77.06, 38.97), (-77.02, 38.97))),  # the street crossing it
            zone(line=frontage),
        ]
        zones = [replace(z, zone_id=f"z{i}") for i, z in enumerate(zones)]
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table}.segment VALUES ('road', ST_GeomFromText(%s, 4326))",
                ["LINESTRING(" + ", ".join(f"{x} {y}" for x, y in frontage) + ")"],
            )
        assert workzones.barred_zones(zones, table) == {"z0"}

    def test_no_table_no_verdict(self) -> None:
        assert workzones.barred_zones([zone(line=ROAD)], "no_such_schema_here") == set()
        assert workzones.barred_zones([], "no_such_schema_here") == set()


@db
def test_a_refresh_stores_the_road_and_the_place(monkeypatch) -> None:
    feed = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "georgia",
                "type": "Feature",
                "properties": {
                    "core_details": {"event_type": "work-zone", "road_names": ["MD 97"]},
                    "vehicle_impact": "some-lanes-closed",
                },
                "geometry": {"type": "MultiPoint", "coordinates": [list(A), list(B)]},
            }
        ],
    }
    calls = []

    def find(a, b, roads):
        calls.append(roads)
        return [list(p) for p in ROAD]

    monkeypatch.delenv(workzones.TOKEN_ENV, raising=False)
    monkeypatch.setattr(workzones, "road_line", find)
    body = json.dumps(feed).encode()
    workzones.refresh(lambda url, timeout: body, lambda s: None, lambda: NOW)
    workzones.refresh(lambda url, timeout: body, lambda s: None, lambda: NOW + timedelta(minutes=5))
    stored = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]["md"]
    assert [tuple(p) for p in stored["zones"][0]["line"]] == ROAD
    assert len(stored["placed"]) == 1 and calls == [("MD 97",)]
    # An Interstate's work zone is not kept (the owner, 2026-10-25, of I-97), nor looked up.
    feed["features"][0]["properties"]["core_details"]["road_names"] = ["I-97"]
    body = json.dumps(feed).encode()
    line = workzones.refresh(lambda url, timeout: body, lambda s: None, lambda: NOW)
    assert line == "work zones: md 0 zones" and len(calls) == 1
    stored = BikeshareFeedCache.objects.get(key=workzones.KEY).payload["feeds"]["md"]
    assert stored["placed"] == {}
    # A zone along a road the map bars is dropped once it is on the road.
    feed["features"][0]["properties"]["core_details"]["road_names"] = ["MD 97"]
    body = json.dumps(feed).encode()
    monkeypatch.setattr(workzones, "barred_zones", lambda zones: {z.zone_id for z in zones})
    line = workzones.refresh(lambda url, timeout: body, lambda s: None, lambda: NOW)
    assert line == "work zones: md 0 zones"
    workzones.forget()
