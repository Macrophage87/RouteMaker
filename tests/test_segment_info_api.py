"""GET /api/segment-info: what is known about the road at a map spot (OWNER-DECISIONS 441a).

Against a real live segment table (the `segment_schemas` fixture); the router's `/locate`
is replaced at `core.segment_info.locate_edges`, the one function that asks it. The
limiter is the real one, on the real database.
"""

from __future__ import annotations

import itertools
import json
import logging

import pytest
from django.db import connection
from test_ratelimit import in_one_window

from core import ratelimit, segment_info
from routemaker import facility, flow

db = pytest.mark.django_db(transaction=True)

INFO = "/api/segment-info"
# Connecticut Avenue NW at Dupont Circle's north side, roughly.
SPOT = (-77.0434, 38.9125)
_next = itertools.count(1)


def fresh_client() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_next) % 250 + 1}"}


def get(client, lat=SPOT[1], lon=SPOT[0], headers=None):
    return client.get(INFO, {"lat": lat, "lon": lon}, **(headers or fresh_client()))


def east(point, metres):
    return (point[0] + metres / 86_700, point[1])


def north(point, metres):
    return (point[0], point[1] + metres / 111_000)


def insert(schema, way, points, **columns) -> None:
    values = {
        "osm_way_id": way,
        "ordinal": 0,
        "stress_tier": 3,
        "stress_rule": "mixed traffic, 30 mph, single lane",
        "stress_assumed": json.dumps([]),
        "map_class": "road",
        **columns,
    }
    if "attr_sources" in values and not isinstance(values["attr_sources"], str):
        values["attr_sources"] = json.dumps(values["attr_sources"])
    if isinstance(values["stress_assumed"], list):
        values["stress_assumed"] = json.dumps(values["stress_assumed"])
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"
    names = ", ".join(values)
    marks = ", ".join("%s" for _ in values)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment ({names}, geometry) "
            f"VALUES ({marks}, ST_GeomFromText(%s, 4326))",
            [*values.values(), wkt],
        )


def edge(way, name=None, use="road", classification="primary"):
    return {
        "edge_info": {"way_id": way, "names": [name] if name else []},
        "edge": {"classification": {"use": use, "classification": classification}},
        "distance": 1.0,
    }


@pytest.fixture
def router(monkeypatch):
    """The router's edges by costing; a costing missing from `answers` answers nothing,
    and `down` makes every call fail as a silent router does."""

    class Fake:
        answers: dict[str, list[dict]] = {}
        down = False
        calls: list[tuple] = []

    def fake(lat, lon, costing):
        Fake.calls.append((lat, lon, costing))
        if Fake.down:
            raise segment_info.RouterSilent("down")
        return Fake.answers.get(costing, [])

    monkeypatch.setattr(segment_info, "locate_edges", fake)
    segment_info.forget_columns()
    yield Fake
    segment_info.forget_columns()


def summary(body) -> list[str]:
    return [f"{r['label']}: {r['value']}" for r in body["summary"]]


def section(body, sid):
    found = [s for s in body["sections"] if s["id"] == sid]
    assert found, (sid, body)
    return {r["label"]: r for r in found[0]["rows"]}


@db
class TestAnswer:
    def test_a_road_with_everything_known(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(
            live,
            101,
            [SPOT, east(SPOT, 100)],
            stress_tier=3,
            stress_rule="mixed traffic, 30 mph, urban multilane",
            volume_source="ddot",
            volume_aadt=18400,
            volume_year=2024,
            road_speed_mph=30,
            road_lanes=2,
            attr_sources={"maxspeed": "dc-roadway-block", "lanes": "osm"},
            facility="lane",
            is_unpaved=False,
            mass_usable_width_m=6.7,
        )
        router.answers = {"bicycle": [edge(101, "Connecticut Avenue Northwest")]}
        response = get(client)
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, max-age=300"
        body = response.json()
        assert body["found"] is True and body["title"] == "Connecticut Avenue Northwest"
        assert body["tier"] == 3 and body["open"] is True and body["osm_way_id"] == 101
        assert body["attribution"] == ["© OpenStreetMap contributors (ODbL)"]
        road = section(body, "road")
        assert road["Name"]["value"] == "Connecticut Avenue Northwest"
        assert road["Kind"]["value"] == "Main road"
        stress = section(body, "stress")
        assert stress["Level"]["value"] == "LTS 3: For experienced cyclists"
        assert stress["Level"]["source"] == "RouteMaker classifier"
        assert stress["Why"]["value"] == "30 mph, mixed traffic, several lanes, city street"
        traffic = section(body, "traffic")
        assert traffic["Lanes"]["value"] == "2 each way"
        assert traffic["Lanes"]["source"] == "OpenStreetMap"
        assert traffic["Speed limit"]["value"] == "30 mph (48 km/h), posted"
        assert "DC Roadway Block" in traffic["Speed limit"]["source"]
        assert traffic["Traffic volume"]["value"] == (
            "18,400 vehicles a day (annual average), 2024 count"
        )
        assert traffic["Traffic volume"]["source"].startswith("DDOT 2024 Traffic Volume")
        riding = section(body, "riding")
        assert riding["Bike facility"]["value"] == "Painted bike lane"
        assert riding["Surface"]["value"] == "Paved"
        assert section(body, "access")["Bike access"]["value"] == "Open to bicycles"
        mass = section(body, "mass")
        assert mass["Usable width"]["value"] == "22 ft (6.7 m)"
        riders = round(flow.level_riders_per_min(6.7))
        assert mass["Riders a minute"]["value"] == f"About {riders:,} on the level"
        # The compact summary: one short line a fact, the lanes not said twice, paved
        # left out on a road, the capacity (the panel shows it on the Mass Ride map only).
        assert body["kind"] == "Main road"
        assert summary(body) == [
            "Traffic stress: LTS 3 · For experienced cyclists",
            "Why: 30 mph, mixed traffic",
            "Speed: 30 mph (48 km/h), posted",
            "Lanes: 2 each way",
            "Traffic: 18,400 a day (DDOT 2024)",
            "Bike lane: Painted",
            "Bikes: Allowed",
            f"Room for: About {riders:,} riders a minute",
        ]
        assert [r["id"] for r in body["summary"]][-1] == "mass"
        # Street View opens on the way itself (OWNER-DECISIONS 441o): the spot is on it here.
        assert body["on_way"] == [round(SPOT[0], 6), round(SPOT[1], 6)]
        # The router was asked at the spot on the way, with the bicycle costing only.
        assert [c[2] for c in router.calls] == ["bicycle"]

    def test_nothing_within_reach_is_no_road_here(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 102, [north(SPOT, 200), east(north(SPOT, 200), 50)])
        body = get(client).json()
        assert body == {
            "found": False,
            "title": "No road here",
            "tier": None,
            "open": None,
            "osm_way_id": None,
            "distance_m": None,
            "on_way": None,
            "kind": None,
            "summary": [],
            "sections": [],
            "attribution": ["© OpenStreetMap contributors (ODbL)"],
        }
        assert router.calls == []

    def test_a_drawn_road_wins_over_a_hidden_sidewalk_a_little_nearer(
        self, client, segment_schemas, router
    ) -> None:
        live, _ = segment_schemas
        insert(live, 103, [north(SPOT, 2), east(north(SPOT, 2), 80)], map_class="hidden")
        insert(live, 104, [north(SPOT, 9), east(north(SPOT, 9), 80)])
        router.answers = {"bicycle": [edge(104, "R Street Northwest")]}
        assert get(client).json()["osm_way_id"] == 104

    def test_an_unnamed_path_says_so(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(
            live,
            105,
            [SPOT, east(SPOT, 50)],
            stress_tier=1,
            stress_rule="trail-class way (cycleway, open to bicycles)",
            is_trail_class=True,
            facility="path",
            is_unpaved=None,
            roadside=True,
        )
        router.answers = {"bicycle": [edge(105, use="cycleway")]}
        body = get(client).json()
        assert body["title"] == "Unnamed path"
        assert section(body, "road")["Name"]["value"] == "No name mapped"
        assert section(body, "road")["Kind"]["value"] == "Bike path"
        assert section(body, "stress")["Level"]["value"] == "LTS 1: Comfortable for everyone"
        assert section(body, "stress")["Why"]["value"] == "Path away from traffic, open to bicycles"
        riding = section(body, "riding")
        assert riding["Surface"]["value"] == (
            "Not mapped; probably paved (a side path beside a road)"
        )
        # A path has no lanes, speed or count to speak of.
        traffic = [s for s in body["sections"] if s["id"] == "traffic"]
        assert traffic == []
        # Nothing about a surface not mapped, no lanes or speed on a path.
        assert summary(body) == [
            "Traffic stress: LTS 1 · Comfortable for everyone",
            "Why: Path away from traffic, open to bicycles",
            "Bikes: Allowed",
        ]

    def test_a_judged_bridge_says_its_deck_and_how_the_map_draws_it(
        self, client, segment_schemas, router
    ) -> None:
        """The Seneca Aqueduct (owner, 2026-10-09): a paved deck inside the unpaved
        towpath, which the map now draws unpaved (`core.stress_tiles.BRIDGE_UNPAVED`)."""
        live, _ = segment_schemas
        insert(
            live,
            106,
            [SPOT, east(SPOT, 50)],
            stress_tier=1,
            stress_rule="trail-class way (path, open to bicycles)",
            is_trail_class=True,
            facility="path",
            is_unpaved=False,
            trail_bridge=2,
        )
        router.answers = {"bicycle": [edge(106, use="path")]}
        riding = section(get(client).json(), "riding")
        assert riding["Surface"]["value"] == (
            "Paved (a bridge deck; the map draws it as part of the unpaved trail)"
        )

    def test_street_view_point_is_snapped_onto_the_way(
        self, client, segment_schemas, router
    ) -> None:
        live, _ = segment_schemas
        # The way runs east-west 20 m north of the spot clicked: the link's point is on it.
        on = north(SPOT, 20)
        insert(live, 120, [east(on, -50), east(on, 50)])
        router.answers = {"bicycle": [edge(120, "R Street Northwest")]}
        body = get(client).json()
        assert body["found"] is True and 19 < body["distance_m"] < 21
        lon, lat = body["on_way"]
        assert abs(lon - SPOT[0]) < 1e-6 and abs(lat - on[1]) < 1e-6

    def test_lanes_on_a_one_way_street_are_in_this_direction(
        self, client, segment_schemas, router
    ) -> None:
        # road_lanes is one direction's count: "3 each way" was wrong on a one-way
        # street such as 9th Street NW (the correctness review's C-1).
        live, _ = segment_schemas
        insert(live, 121, [SPOT, east(SPOT, 80)], road_lanes=3, road_oneway=True)
        router.answers = {"bicycle": [edge(121, "9th Street Northwest")]}
        body = get(client).json()
        assert "Lanes: 3 in this direction" in summary(body)
        assert section(body, "traffic")["Lanes"]["value"] == (
            "3 in this direction (a one-way street, or one side of a divided road)"
        )

    def test_lanes_on_a_two_way_street_are_each_way(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 122, [SPOT, east(SPOT, 80)], road_lanes=2, road_oneway=False)
        router.answers = {"bicycle": [edge(122, "16th Street Northwest")]}
        body = get(client).json()
        assert "Lanes: 2 each way" in summary(body)
        assert section(body, "traffic")["Lanes"]["value"] == "2 each way"

    def test_assumed_lanes_on_a_one_way_street(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 123, [SPOT, east(SPOT, 80)], stress_assumed=["lanes"], road_oneway=True)
        router.answers = {"bicycle": [edge(123, "Corcoran Street Northwest")]}
        body = get(client).json()
        assert "Lanes: 1 in this direction, assumed" in summary(body)
        assert (
            section(body, "traffic")["Lanes"]["value"] == "Not mapped; assumed 1 in this direction"
        )

    def test_assumed_speed_and_lanes_say_assumed(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(
            live,
            106,
            [SPOT, east(SPOT, 50)],
            stress_tier=2,
            stress_rule="mixed traffic, 20 mph or below, single lane",
            stress_assumed=["maxspeed", "lanes", "parking"],
        )
        router.answers = {
            "bicycle": [edge(106, "Q Street Northwest", classification="residential")]
        }
        body = get(client).json()
        traffic = section(body, "traffic")
        assert traffic["Speed limit"]["value"] == "Not posted in the data; assumed 20 mph or below"
        assert traffic["Lanes"]["value"] == "Not mapped; assumed 1 each way"
        assert traffic["Traffic volume"]["value"] == "No count"
        assert section(body, "road")["Kind"]["value"] == "Residential street"
        # Assumed figures say so; no count is left out, not printed as "none".
        assert summary(body) == [
            "Traffic stress: LTS 2 · Fine for adults",
            "Why: 20 mph or below, mixed traffic",
            "Speed: 20 mph (32 km/h), assumed",
            "Lanes: 1 each way, assumed",
            "Bikes: Allowed",
        ]

    def test_a_closed_way_says_why(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 107, [SPOT, east(SPOT, 50)], bike_access_reason="military")
        # Not among the bicycle costing's edges: the graph keeps bicycles off.
        router.answers = {"bicycle": [], "pedestrian": [edge(107, "Patrol Road")]}
        body = get(client).json()
        assert body["open"] is False and body["title"] == "Patrol Road"
        access = section(body, "access")["Bike access"]
        assert access["value"].startswith("Closed: inside a military area")
        assert access["source"] == "RouteMaker classifier"
        assert summary(body)[-1] == "Bikes: Not allowed — military area"

    def test_a_mountain_bike_trail_says_not_used_for_routes(
        self, client, segment_schemas, router
    ) -> None:
        """OWNER-DECISIONS 452a: drawn in the not-for-routes look, and said so; honest that
        Gravel and Mountain Goat (the off-road graph) do use it."""
        live, _ = segment_schemas
        insert(
            live,
            120,
            [SPOT, east(SPOT, 50)],
            stress_tier=1,
            stress_rule="trail-class way (path, not open to bicycles)",
            is_trail_class=True,
            is_unpaved=True,
            bike_access_reason="mtb",
            mtb_only=True,
        )
        router.answers = {"bicycle": [], "pedestrian": [edge(120, "Wakefield Loop", use="path")]}
        body = get(client).json()
        assert body["open"] is False and body["osm_way_id"] == 120
        assert summary(body)[-1] == (
            "Bikes: Mountain-bike trail, not used for routes (Gravel and Mountain Goat may use it)"
        )
        access = section(body, "access")["Bike access"]
        assert access["value"] == (
            "Closed: a mountain-bike trail, not used for routes except by the Gravel and"
            " Mountain Goat ride types (drawn as a thin grey dotted line when the"
            " Mountain-bike trails map layer is on)"
        )

    def test_the_mtb_property_alone_marks_one(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 121, [SPOT, east(SPOT, 50)], is_trail_class=True, mtb_only=True)
        # Closed on the standard graph, as the class is.
        router.answers = {"bicycle": [], "pedestrian": [edge(121, use="path")]}
        body = get(client).json()
        assert summary(body)[-1] == (
            "Bikes: Mountain-bike trail, not used for routes (Gravel and Mountain Goat may use it)"
        )

    def test_a_normal_way_a_little_further_wins_over_a_nearer_mountain_bike_trail(
        self, client, segment_schemas, router
    ) -> None:
        live, _ = segment_schemas
        insert(
            live,
            122,
            [north(SPOT, 2), east(north(SPOT, 2), 80)],
            is_trail_class=True,
            bike_access_reason="mtb",
            mtb_only=True,
        )
        insert(live, 123, [north(SPOT, 9), east(north(SPOT, 9), 80)])
        router.answers = {"bicycle": [edge(123, "R Street Northwest")]}
        assert get(client).json()["osm_way_id"] == 123

    def test_an_owner_reopened_way_says_so(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(live, 108, [SPOT, east(SPOT, 50)], bike_access_reason="override_open")
        router.answers = {"bicycle": [edge(108, "Jeff Todd Way")]}
        access = section(get(client).json(), "access")["Bike access"]
        assert access["value"].startswith("Open: reopened by an owner override")
        assert access["source"] == "Owner override"

    def test_an_owner_rated_corridor(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(
            live,
            109,
            [SPOT, east(SPOT, 50)],
            stress_tier=5,
            stress_rule="override: stress adjustment east-anacostia-suitland-parkway",
            stress_adjustment_id="east-anacostia-suitland-parkway",
            stress_computed_tier=3,
            stress_adjustment_direction="up",
            stress_adjustment_category="speed",
            stress_adjustment_note="Freeway-grade highway with fast through traffic.",
            stress_adjustment_display="route_only",
        )
        router.answers = {"bicycle": [edge(109, "Suitland Parkway")]}
        stress = section(get(client).json(), "stress")
        assert stress["Level"]["value"] == "Avoid"
        assert stress["Level"]["source"] == "Owner override"
        assert stress["Why"]["value"] == "Owner-rated corridor"
        assert stress["Before the override"]["value"] == "LTS 3: For experienced cyclists"
        assert stress["Owner's reason"]["value"] == "Speed"
        # A route-only note is never shown on a map click.
        assert "Note" not in stress

    def test_a_map_note_is_shown(self, client, segment_schemas, router) -> None:
        live, _ = segment_schemas
        insert(
            live,
            110,
            [SPOT, east(SPOT, 50)],
            stress_rule="override: stress adjustment x",
            stress_adjustment_id="x",
            stress_adjustment_note="Blind corner at the ramp.",
            stress_adjustment_display="map",
        )
        stress = section(get(client).json(), "stress")
        assert stress["Note"]["value"] == "Blind corner at the ramp."

    def test_a_silent_router_still_answers_from_the_table(
        self, client, segment_schemas, router
    ) -> None:
        live, _ = segment_schemas
        insert(
            live, 111, [SPOT, east(SPOT, 50)], map_class="barred", bike_access_reason="bicycle_no"
        )
        router.down = True
        body = get(client).json()
        assert body["found"] is True and body["title"] == "Unnamed road"
        assert body["open"] is False
        assert section(body, "access")["Bike access"]["value"].startswith("Closed: no bicycles")
        assert section(body, "road")["Kind"]["value"] == "Road"

    def test_an_old_table_answers_with_what_it_has(self, client, segment_schemas, router) -> None:
        """The live table today predates the capacity, trait and access columns."""
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            for column in (
                "mass_usable_width_m",
                "bike_access_reason",
                "trail_name",
                "roadside",
                "walk_bike",
            ):
                cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN {column} CASCADE")
        insert(live, 112, [SPOT, east(SPOT, 50)])
        router.answers = {"pedestrian": [edge(112, "Private Drive")]}
        body = get(client).json()
        assert body["found"] is True and body["open"] is False
        mass = section(body, "mass")
        assert mass["Usable width"]["value"] == "Available after the next data update"
        assert mass["Riders a minute"]["value"] == "Available after the next data update"
        assert section(body, "access")["Bike access"]["value"] == (
            "Closed to bicycles; the reason is available after the next data update"
        )
        # Not allowed is always said, even with no reason yet; no capacity line.
        assert summary(body)[-1] == "Bikes: Not allowed"

    def test_the_spot_is_never_logged(self, client, segment_schemas, router, caplog) -> None:
        live, _ = segment_schemas
        insert(live, 113, [SPOT, east(SPOT, 50)])
        router.down = True
        with caplog.at_level(logging.DEBUG):
            assert get(client).status_code == 200
            assert get(client, lat=45.0, lon=-77.0).status_code == 400
        text = caplog.text
        assert "38.9125" not in text and "77.0434" not in text and "45.0" not in text


@db
class TestRefusals:
    def test_outside_the_coverage_is_400(self, client, segment_schemas, router) -> None:
        response = get(client, lat=40.44, lon=-80.0)
        assert response.status_code == 400
        assert set(response.json()) == {"error"}

    def test_missing_coordinates_are_400(self, client, segment_schemas, router) -> None:
        response = client.get(INFO, {"lat": 38.9}, **fresh_client())
        assert response.status_code == 400

    def test_a_foreign_page_is_refused_uncounted(self, client, segment_schemas, router) -> None:
        response = get(client, headers={**fresh_client(), "HTTP_SEC_FETCH_SITE": "cross-site"})
        assert response.status_code == 403
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM rate_limit_window WHERE scope LIKE 'segment-info%%'"
            )
            assert cursor.fetchone()[0] == 0

    def test_the_21st_in_ten_seconds_is_429(self, client, segment_schemas, router) -> None:
        def attempt(n):
            address = f"203.0.113.{90 + n}"
            key = ratelimit.client_key(address)
            for _ in range(ratelimit.SEGMENT_INFO_BURST.requests):
                ratelimit.hit(ratelimit.SEGMENT_INFO_BURST, key)
            return get(client, headers={"HTTP_X_FORWARDED_FOR": address})

        refused = in_one_window(ratelimit.SEGMENT_INFO_BURST.window_s, attempt)
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= ratelimit.SEGMENT_INFO_BURST.window_s

    def test_the_limits(self) -> None:
        assert (ratelimit.SEGMENT_INFO.requests, ratelimit.SEGMENT_INFO.window_s) == (60, 60)


class TestWords:
    @pytest.mark.parametrize(
        ("rule", "words"),
        [
            ("mixed traffic, 35 mph or above", "35 mph or above, mixed traffic"),
            (
                "mixed traffic, 25 mph, single lane, low volume",
                "25 mph, mixed traffic, one lane each way, light traffic",
            ),
            (
                "legal but avoid: expressway posted 55 mph (Furth: mixed traffic, 35 mph or above)",
                "Avoid: highway-like road (posted 55 mph)",
            ),
            (
                "motor-only classification (motorway_link)",
                "Highway-like road for motor traffic (motorway link)",
            ),
            ("override: stress adjustment moco-lts5-georgia-avenue", "Owner-rated corridor"),
            ("named corridor: c1, e2", "Owner-rated corridor"),
            ("trail-class way (footway)", "Path away from traffic"),
            (
                "trail-class way (path, not open to bicycles)",
                "Path away from traffic, not open to bicycles",
            ),
            ("separated track alongside", "Separated bike track beside the road"),
            ("bike lane, 35 mph", "Bike lane, 35 mph"),
            (
                "motor traffic restricted (access=private), LTS 2 at most",
                "Little motor traffic (access=private), so LTS 2 at most",
            ),
            (
                "closed to motor traffic: an off-road path"
                " (was: mixed traffic, 30 mph, single lane)",
                "Closed to motor traffic, so rated as a path",
            ),
        ],
    )
    def test_rules_in_plain_words(self, rule, words) -> None:
        assert segment_info.rule_words(rule) == words

    def test_every_tier_has_its_step_words(self) -> None:
        assert [segment_info.tier_text(t) for t in range(1, 6)] == [
            "LTS 1: Comfortable for everyone",
            "LTS 2: Fine for adults",
            "LTS 3: For experienced cyclists",
            "LTS 4: High stress: busy, fast traffic",
            "Avoid",
        ]

    def test_every_reason_the_rebuild_writes_has_words(self) -> None:
        from pipeline.restricted_areas import MILITARY_NO_BICYCLE, SECURED_NO_BICYCLE
        from routemaker import cbd, singletrack, trailaccess, zoo

        written = {
            *trailaccess.TAG_REASONS,
            MILITARY_NO_BICYCLE,
            SECURED_NO_BICYCLE,
            cbd.NO_BICYCLE,
            singletrack.NO_BICYCLE,
            zoo.NO_BICYCLE,
            "override_open",
            "override_closed",
            "bicycle_no",
            "bicycle_use_sidepath",
            "private",
            "impassable",
            "motorway",
            "motorroad",
        }
        assert written <= set(segment_info.ACCESS_WORDS), written - set(segment_info.ACCESS_WORDS)
        for _open, words in segment_info.ACCESS_WORDS.values():
            assert words.startswith(("Open", "Closed")), words
        closed = {k for k, (open_, _w) in segment_info.ACCESS_WORDS.items() if not open_}
        assert closed == set(segment_info.ACCESS_SHORT), closed ^ set(segment_info.ACCESS_SHORT)

    def test_choose_prefers_a_way_to_ride_then_a_mountain_bike_trail_then_a_hidden_one(
        self,
    ) -> None:
        def way(i, d, **kw):
            return {"osm_way_id": i, "distance_m": d, "map_class": "road", **kw}

        mtb = {"bike_access_reason": "mtb", "mtb_only": True}
        hidden = {"map_class": "hidden"}
        choose = segment_info.choose
        # An MTB trail nearest, a normal way within DRAWN_PREFERENCE_M: the normal way.
        assert choose([way(1, 2, **mtb), way(2, 12)])["osm_way_id"] == 2
        # Past DRAWN_PREFERENCE_M the trail the rider clicked is described.
        assert choose([way(1, 2, **mtb), way(2, 20)])["osm_way_id"] == 1
        # The only thing near: still described.
        assert choose([way(1, 5, **mtb)])["osm_way_id"] == 1
        # A hidden sidewalk nearest: a normal way beats a nearer MTB trail; an MTB trail
        # beats the hidden way when it is all the map draws there.
        assert choose([way(1, 1, **hidden), way(2, 3, **mtb), way(3, 10)])["osm_way_id"] == 3
        assert choose([way(1, 1, **hidden), way(2, 3, **mtb)])["osm_way_id"] == 2
        # A normal way nearest is never passed over.
        assert choose([way(3, 2), way(4, 3, **mtb)])["osm_way_id"] == 3
        # A barred way (a closed hiking trail) is not drawn as one to ride either: it
        # ranks with the MTB trail, so the nearer of the two is described.
        assert choose([way(1, 2, **mtb), way(2, 10, map_class="barred")])["osm_way_id"] == 1
        assert choose([way(1, 2, map_class="barred"), way(2, 10, **mtb)])["osm_way_id"] == 1
        assert choose([way(1, 2, map_class="barred"), way(2, 10)])["osm_way_id"] == 2
        # Rated singletrack is `mtb_only` too, but hidden, and says so in its own words.
        assert not segment_info.is_mtb_trail(way(5, 1, map_class="hidden", mtb_only=True))
        assert segment_info.is_mtb_trail(way(6, 1, mtb_only=True))

    def test_the_summary_why_drops_what_lanes_says(self) -> None:
        assert segment_info.why_short("mixed traffic, 30 mph, urban multilane") == (
            "30 mph, mixed traffic"
        )
        assert segment_info.why_short("mixed traffic, 35 mph or above, multilane") == (
            "35 mph or above, mixed traffic"
        )
        assert segment_info.why_short("bike lane, 25 mph, single lane") == "Bike lane, 25 mph"
        assert segment_info.why_short("") is None


class TestAccessReason:
    @pytest.mark.parametrize(
        ("tags", "kwargs", "reason"),
        [
            ({"highway": "residential"}, {}, None),
            ({"highway": "primary", "bicycle": "no"}, {}, "bicycle_no"),
            ({"highway": "primary", "bicycle": "use_sidepath"}, {}, "bicycle_use_sidepath"),
            ({"highway": "motorway"}, {}, "motorway"),
            ({"highway": "trunk", "motorroad": "yes"}, {}, "motorroad"),
            ({"highway": "service", "access": "private"}, {}, "private"),
            ({"highway": "service", "access": "private", "bicycle": "yes"}, {}, None),
            ({"highway": "service"}, {"no_bicycle": "military"}, "military"),
            ({"highway": "path", "bicycle": "yes"}, {"overridden": True}, "override_open"),
            ({"highway": "path", "bicycle": "no"}, {"overridden": True}, "override_closed"),
            # A closure rule that still closed an overridden way keeps its own reason.
            (
                {"highway": "path", "bicycle": "yes"},
                {"overridden": True, "no_bicycle": "secured"},
                "secured",
            ),
        ],
    )
    def test_reasons(self, tags, kwargs, reason) -> None:
        assert facility.bike_access_reason(tags, **kwargs) == reason


@pytest.mark.parametrize(
    ("row", "words"),
    [
        (
            {"is_unpaved": False, "trail_bridge": 2},
            "Paved (a bridge deck; the map draws it as part of the unpaved trail)",
        ),
        (
            {"is_unpaved": True, "trail_bridge": 1},
            "Unpaved (a bridge deck; the map draws it as part of the paved trail)",
        ),
        # The deck agrees with its trail, or the way is no judged bridge: the plain words.
        ({"is_unpaved": True, "trail_bridge": 2}, "Unpaved"),
        ({"is_unpaved": False, "trail_bridge": 1}, "Paved"),
        ({"is_unpaved": False, "trail_bridge": 0}, "Paved"),
        ({"is_unpaved": False}, "Paved"),
        ({"is_unpaved": None, "trail_bridge": 2}, "Not mapped"),
    ],
)
def test_the_surface_words_name_a_bridge_drawn_in_its_trails_surface(row, words) -> None:
    from core.segment_info import surface_words

    assert surface_words(row) == words
