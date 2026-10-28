"""POST /api/route's `description` (OWNER-DECISIONS item 220), through the real
view, the real segment table and a stand-in router: the route in words, built
from the trace the plan already made (no extra router call), additive to the
contract, and absent rather than fatal when it cannot be built."""

from __future__ import annotations

import copy

import pytest
from test_route_api import (
    VERTICES,
    FakeRouter,
    encode_polyline6,
    good_body,
    post,
    route_answer,
)
from test_route_intersections import arterial, locate_answer, world  # noqa: F401

from core import api, presets, routing
from routemaker import calm, describe

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def named_world(names=("Quiet Street",), **kwargs):
    """The arterial world, its two edges of the quiet street named."""
    fake = world(**kwargs)
    for edge in fake.answers["trace_attributes"]["edges"]:
        if names:
            edge["names"] = list(names)
    return fake


def no_line(shape, at, nodes):
    """`routing._line_headings` where the route's line is not read: the edges' headings."""
    return None, None, at, at


@db
@pytest.mark.usefixtures("arterial")
class TestInTheAnswer:
    def test_the_route_is_described_stretch_by_stretch(self, client, router):
        router(named_world())
        body = post(client, good_body()).json()
        entries = body["description"]
        assert [e["kind"] for e in entries] == ["stretch", "junction"]
        stretch, junction = entries
        assert stretch["street"] == "Quiet Street"
        # The map says no facility: "none", not unknown (round-2 D28; was None).
        assert stretch["tier"] == 2 and stretch["facility"] == "none"
        assert stretch["turn"] is None
        assert stretch["text"] == (
            "0.0 to 1.7 mi (0.0 to 2.7 km): Quiet Street, fairly low stress (LTS 2)."
        )
        assert junction["severity"] == "red"
        assert junction["text"] == (
            "At 0.6 mi (0.9 km): Cross Arterial (LTS 4), no signal mapped "
            "(Very high stress junction)."
        )

    def test_the_stretches_add_up_to_the_routes_length(self, client, router):
        router(named_world(length_km=2.65))
        body = post(client, good_body()).json()
        stretches = [e for e in body["description"] if e["kind"] == "stretch"]
        assert stretches[0]["from_m"] == 0
        assert stretches[-1]["to_m"] == round(body["distance_m"])

    def test_it_costs_no_extra_router_call(self, client, router, monkeypatch):
        """The street names ride on the trace the plan makes anyway: the same
        calls are made whether the description is built or not."""
        with_it = router(named_world())
        post(client, good_body())
        monkeypatch.setattr(routing, "describe_route", lambda *args, **kwargs: None)
        without = router(named_world())
        post(client, good_body())
        assert with_it.endpoints() == without.endpoints()
        traces = [p for url, p in with_it.calls if url.endswith("/trace_attributes")]
        assert traces and all("edge.names" in p["filters"]["attributes"] for p in traces)

    def test_missing_names_are_unnamed(self, client, router):
        router(named_world(names=()))
        entries = post(client, good_body()).json()["description"]
        assert entries[0]["street"] == "unnamed road"
        assert entries[0]["text"].endswith("unnamed road, fairly low stress (LTS 2).")

    def test_a_trace_without_headings_or_names_still_describes(self, client, router):
        fake = named_world(names=())
        for edge in fake.answers["trace_attributes"]["edges"]:
            for key in ("names", "begin_heading", "end_heading", "use"):
                edge.pop(key, None)
        router(fake)
        assert post(client, good_body()).json()["description"][0]["kind"] == "stretch"

    def test_a_street_change_is_a_turn_with_its_signal(self, client, router, monkeypatch):
        # The world's line runs straight: the edges' headings stand in for the turn.
        monkeypatch.setattr(routing, "_line_headings", no_line)
        fake = named_world()
        edges = fake.answers["trace_attributes"]["edges"]
        edges[1]["names"] = ["Second Street"]
        edges[1]["begin_heading"] = 0
        edges[1]["end_heading"] = 0
        fake.locate = locate_answer(signal=True)
        router(fake)
        entries = post(client, good_body()).json()["description"]
        assert [e["street"] for e in entries] == ["Quiet Street", "Second Street"]
        assert entries[1]["turn"]["movement"] == "left"
        assert entries[1]["turn"]["onto"] == "Second Street"
        assert entries[1]["text"].split(": ")[1].startswith("Left onto Second Street")

    def test_a_bear_is_answered_in_both_lists(self, client, router, monkeypatch):
        # v0.7.0 answered 500 here: the response schema had no bears.
        monkeypatch.setattr(routing, "_line_headings", no_line)
        fake = named_world()
        edges = fake.answers["trace_attributes"]["edges"]
        edges[1]["names"] = ["Second Street"]
        edges[1]["begin_heading"] = edges[0]["end_heading"] - 30
        edges[1]["end_heading"] = edges[1]["begin_heading"]
        router(fake)
        response = post(client, good_body())
        assert response.status_code == 200
        for view in ("description", "description_overview"):
            turns = [e["turn"]["movement"] for e in response.json()[view] if e.get("turn")]
            assert "bear_left" in turns, view

    @pytest.mark.parametrize(
        "preset",
        sorted(set(presets.PRESETS) - {*presets.BIKESHARE_PRESETS, *presets.TRANSIT_PRESETS}),
    )
    def test_every_preset_is_described(self, client, router, preset):
        router(named_world())
        body = post(client, good_body(preset)).json()
        entries = body["description"]
        assert entries and all(isinstance(e["text"], str) and e["text"] for e in entries)
        stretches = [e for e in entries if e["kind"] == "stretch"]
        assert stretches[-1]["to_m"] == round(body["distance_m"])

    def test_the_route_is_answered_without_it_where_it_cannot_be_built(
        self, client, router, monkeypatch
    ):
        def broken(*args, **kwargs):
            raise RuntimeError("no")

        monkeypatch.setattr(describe, "describe_both", broken)
        router(named_world())
        response = post(client, good_body())
        assert response.status_code == 200
        assert response.json()["description"] is None
        assert response.json()["description_overview"] is None


@pytest.fixture
def segments_two(segment_schemas):
    """Way 101 under both legs of a two-leg plan."""
    from django.db import connection

    live, _staging = segment_schemas
    with connection.cursor() as cursor:
        for ordinal, line in enumerate((VERTICES[0:3], VERTICES[2:5])):
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (101, %s, ST_GeomFromText(%s, 4326), 1, 'test')",
                [ordinal, wkt],
            )
    return live


@db
class TestVias:
    def test_a_via_point_is_an_entry_and_splits_the_stretch(self, client, segments_two, router):
        first, second = VERTICES[:3], VERTICES[2:]
        trace = {
            "units": "kilometers",
            "edges": [
                {
                    "way_id": 101,
                    "begin_shape_index": 0,
                    "end_shape_index": 2,
                    "length": 1.0,
                    "names": ["Quiet Street"],
                },
            ],
        }
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 1.0, [1.0]), (second, 1.0, [1.0])]),
                    "trace_attributes": [
                        {**trace, "shape": encode_polyline6(first)},
                        {**copy.deepcopy(trace), "shape": encode_polyline6(second)},
                    ],
                }
            )
        )
        body = {
            "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[4])],
            "preset": "default",
        }
        entries = post(client, body).json()["description"]
        assert [e["kind"] for e in entries] == ["stretch", "via", "stretch"]
        assert entries[1]["text"].startswith("Stop 1 at 0.6 mi")
        assert entries[0]["to_m"] == entries[1]["from_m"] == entries[2]["from_m"]

    def test_a_mass_ride_group_is_split_at_the_stop(
        self, client, segments_two, router, monkeypatch
    ):
        """OWNER-DECISIONS 247: the plan numbers a Mass Ride's crossing groups
        again with the stops (where each leg ends along the traced length), so
        a group the search's reading ran across the stop is two, one each side,
        in the junction list and the description alike."""
        from routemaker import intersections as m

        first, second = VERTICES[:3], VERTICES[2:]
        trace = {
            "units": "kilometers",
            "edges": [
                {
                    "way_id": 101,
                    "begin_shape_index": 0,
                    "end_shape_index": 2,
                    "length": 1.0,
                    "names": ["Quiet Street"],
                },
            ],
        }
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 1.0, [1.0]), (second, 1.0, [1.0])]),
                    "trace_attributes": [
                        # Each leg traced for every costing the plan asks with.
                        *[
                            {**copy.deepcopy(trace), "shape": encode_polyline6(leg)}
                            for _ in range(4)
                            for leg in (first, second)
                        ]
                    ],
                }
            )
        )

        def signal(at_m: float, name: str) -> m.Event:
            return m.Event(
                at_m,
                VERTICES[2][0],
                VERTICES[2][1],
                "crossing",
                m.Movement.STRAIGHT,
                m.Control.SIGNAL,
                150.0,
                m.ORANGE,
                "Crossing a busy road (LTS 3), traffic signal",
                3,
                True,
                group_severity=True,
                road_names=frozenset({name.lower()}),
                road_display=(name,),
            )

        # As the search would read the whole trip: one group, across the stop.
        events = m.number_groups(
            [signal(x, f"{n}th Street") for n, x in enumerate((600.0, 800.0, 1200.0, 1400.0))]
        )
        assert [e.group for e in events] == [1, 1, 1, 1]
        monkeypatch.setattr(routing, "_events", lambda *args: list(events))
        body = {
            "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[4])],
            "preset": "mass-ride",
        }
        answer = post(client, body).json()
        assert [r["group"] for r in answer["intersections"]] == [1, 1, 2, 2]
        groups = answer["intersection_groups"]
        assert [(g["from_m"], g["to_m"]) for g in groups] == [(600, 800), (1200, 1400)]
        for view in ("description", "description_overview"):
            kinds = [e["kind"] for e in answer[view] if e["kind"] != "stretch"]
            assert kinds == ["junction", "via", "junction"], view


class TestSchema:
    def schema(self):
        return api.RouteOut.model_json_schema()

    def test_description_is_an_optional_field_of_the_route(self):
        schema = self.schema()
        assert "description" in schema["properties"]
        # Additive: a client that does not know it, or an answer without it, is fine.
        assert "description" not in schema.get("required", [])

    def test_an_entry_has_the_fields_the_contract_names(self):
        entry = api.DescriptionEntryOut.model_json_schema()
        assert set(entry["properties"]) == {
            "kind",
            "from_m",
            "to_m",
            "from_mi",
            "to_mi",
            "street",
            "tier",
            "facility",
            "turn",
            "severity",
            "via",
            "group",
            "surface",
            "text",
            "text_lanes_hidden",
            "relation_name",
            # v0.8.2: a closure's source and until when, in small print.
            "citation",
            # Round-2 audit R2: an Avoid-rated junction's reason, beside its name in `street`.
            "reason",
            # Round-2 audit D26: whether a stretch's road is one-way where it ends.
            "oneway",
        }
        # "avoid": an Avoid-rated junction ahead (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307).
        # "workzone": a live work zone on the route (FOLLOWUP-WORKZONES, 341-349).
        # "climb": a categorised climb ridden where the hill seek ran (FOLLOWUP-HILL-SEEK, 205).
        # "hazard": cobblestones or rails in the road ridden (v0.10.0, `core.route_hazards`).
        kinds = ["stretch", "junction", "via", "walk", "avoid", "workzone", "climb", "hazard"]
        assert entry["properties"]["kind"]["enum"] == kinds
        for field in (
            "kind",
            "from_m",
            "to_m",
            "from_mi",
            "to_mi",
            "street",
            "tier",
            "facility",
            "turn",
            "text",
        ):
            assert field in entry["required"]

    def test_every_entry_the_describer_makes_validates(self):
        atoms = [
            describe.Atom(500.0, "3", "none", ("A St",), "road", 0.0, 0.0),
            describe.Atom(500.0, "1", "path", (), "cycleway", 270.0, 270.0),
        ]
        for entry in describe.describe([atoms, 400.0]):
            api.DescriptionEntryOut.model_validate(entry)

    def test_a_fork_and_a_junction_shape_reach_the_client(self):
        """`stay` and `shape` are fields of the turn: the response schema keeps only its
        own fields, and `stay` was dropped before v0.10.0."""
        atoms = [
            describe.Atom(500.0, "2", "none", ("A St",), "road", 0.0, 0.0),
            describe.Atom(
                500.0,
                "2",
                "none",
                ("A St",),
                "road",
                45.0,
                45.0,
                fork="bear_right",
                others=((0.0, "road"), (270.0, "road"), (90.0, "road")),
            ),
        ]
        entry = describe.describe([atoms])[1]
        turn = api.DescriptionEntryOut.model_validate(entry).model_dump()["turn"]
        assert turn["stay"] is True
        assert turn["shape"] == {"out": 45, "others": [-90, 0, 90], "main": None, "ring": None}

    def test_an_answer_without_it_still_validates_and_has_none(self):
        assert api.RouteOut.model_fields["description"].default is None


class TestPieces:
    """The names, use and headings the trace carries onto its pieces."""

    def trace(self, **edge):
        base = {"way_id": 7, "begin_shape_index": 0, "end_shape_index": 2, "length": 0.4}
        return {
            "units": "kilometers",
            "shape": encode_polyline6(VERTICES[:3]),
            "edges": [{**base, **edge}],
        }

    def test_each_piece_of_an_edge_carries_its_names_use_and_headings(self):
        pieces = routing.pieces_of_trace(
            self.trace(
                names=["Bethesda Avenue", "MD 191"],
                use="cycleway",
                begin_heading=80,
                end_heading=100,
            )
        )
        assert len(pieces) == 2
        for piece in pieces:
            assert piece.names == ("Bethesda Avenue", "MD 191")
            assert piece.use == "cycleway"
            assert (piece.heading_in, piece.heading_out) == (80.0, 100.0)

    def test_an_edge_without_them_has_none(self):
        (first, *_rest) = routing.pieces_of_trace(self.trace())
        assert first.names == () and first.use == ""
        assert first.heading_in is None and first.heading_out is None

    def test_blank_and_odd_names_are_dropped(self):
        (first, *_rest) = routing.pieces_of_trace(self.trace(names=["", "  ", 5, "Main St"]))
        assert first.names == ("Main St",)

    def test_a_degenerate_edge_keeps_its_names_too(self):
        trace = self.trace(names=["Main St"], begin_shape_index=1, end_shape_index=1)
        (piece,) = routing.pieces_of_trace(trace)
        assert piece.names == ("Main St",)

    def test_each_piece_carries_its_bearing_unwrapped_along_the_trace(self):
        # North 40 m, then a hairpin right: east 10 m, then a little west of south 40 m. The
        # bearings run on past 180 (0, 90, about 190), never back through 0.
        lat = 39.08
        north = 40 / 111_195
        east = 10 / (111_195 * 0.776)
        shape = [
            (-77.08, lat),
            (-77.08, lat + north),
            (-77.08 + east, lat + north),
            (-77.08 + east * 0.4, lat + north * 0.05),
        ]
        trace = {
            "units": "kilometers",
            "shape": encode_polyline6(shape),
            "edges": [
                {"way_id": 1, "begin_shape_index": 0, "end_shape_index": 1, "length": 0.04},
                {"way_id": 2, "begin_shape_index": 1, "end_shape_index": 3, "length": 0.05},
            ],
        }
        bearings = [p.bearing for p in routing.pieces_of_trace(trace)]
        assert bearings[0] == pytest.approx(0.0, abs=1)
        assert bearings[1] == pytest.approx(90.0, abs=1)
        assert 185 < bearings[2] < 215

    def test_the_new_fields_are_not_part_of_a_pieces_identity(self):
        a = routing.Piece(1, -77.0, 38.9, 10.0, names=("A",), use="road", heading_in=1.0)
        assert a == routing.Piece(1, -77.0, 38.9, 10.0)


class TestDescribeRoute:
    def pieces(self):
        return [
            routing.Piece(1, -77.0, 38.9, 400.0, ("A St",), "road", 0.0, 0.0),
            routing.Piece(2, -77.0, 38.9, 600.0, ("B St",), "road", 270.0, 270.0),
        ]

    def test_the_pieces_and_their_classes_are_the_routes_words(self):
        classes = [("3", "none"), ("1", "path")]
        entries, overview = routing.describe_route(
            [(0, 2)], self.pieces(), classes, None, {"length": 1.0}
        )
        assert [e["tier"] for e in overview] == [3, 1]
        assert [e["street"] for e in entries] == ["A St", "B St"]
        assert [e["tier"] for e in entries] == [3, 1]
        assert [e["facility"] for e in entries] == ["none", "path"]  # known, round-2 D28
        assert entries[1]["turn"]["movement"] == "left"
        assert entries[-1]["to_m"] == 1000

    def test_a_stretch_says_whether_its_road_is_one_way_where_it_ends(self):
        # Round-2 audit D26 (owner-approved 2026-10-27): Ride says "the destination is
        # across ..." only on a known two-way road; the map's `road_oneway`, else None.
        classes = [routing.PieceClass("3", "none", oneway=True), routing.PieceClass("3", "none")]
        entries, overview = routing.describe_route(
            [(0, 2)], self.pieces(), classes, None, {"length": 1.0}
        )
        assert [e["oneway"] for e in entries] == [True, None]
        assert overview[-1]["oneway"] is None
        two_way = [routing.PieceClass("3", "none"), routing.PieceClass("3", "none", oneway=False)]
        entries, _overview = routing.describe_route(
            [(0, 2)], self.pieces(), two_way, None, {"length": 1.0}
        )
        assert entries[-1]["oneway"] is False
        for entry in entries:
            api.DescriptionEntryOut.model_validate(entry)

    def test_an_unnamed_way_takes_its_street_side_name(self):
        # v0.7.0 "Go riding fixes" item 4: a piece of a way with no name, and a name from
        # the rebuild (`segment.sidepath_name`), is said by that name; another stays "path".
        pieces = [
            routing.Piece(1, -77.0, 38.9, 400.0, ("R Street Northwest",), "road", 90.0, 90.0),
            routing.Piece(7, -77.0, 38.9, 600.0, (), "cycleway", 0.0, 0.0),
            routing.Piece(8, -77.0, 38.9, 600.0, (), "cycleway", 0.0, 0.0),
        ]
        classes = [("2", "none"), ("1", "protected"), ("1", "path")]
        entries, _overview = routing.describe_route(
            [(0, 3)],
            pieces,
            classes,
            None,
            {"length": 1.6},
            None,
            {7: "9th Street Northwest protected bike lane"},
        )
        assert [e["street"] for e in entries] == [
            "R Street Northwest",
            "9th Street Northwest protected bike lane",
            "path",
        ]
        assert "unnamed" not in " ".join(e["text"] for e in entries)

    def test_a_stretch_named_only_by_its_relation_is_flagged(self):
        """The owner, 2026-10-16: a relation's name is the description's, but the ride
        gives no "Continue onto" for it; one a way of the route carries itself is not
        flagged."""
        pieces = [
            routing.Piece(1, -77.0, 38.9, 600.0, ("Custis Trail",), "cycleway", 90.0, 90.0),
            routing.Piece(7, -77.0, 38.9, 600.0, (), "cycleway", 90.0, 90.0),
            routing.Piece(8, -77.0, 38.9, 600.0, (), "cycleway", 90.0, 90.0),
        ]
        classes = [("1", "path")] * 3
        entries, overview = routing.describe_route(
            [(0, 3)],
            pieces,
            classes,
            None,
            {"length": 1.8},
            None,
            {
                7: describe.RelationName("Mount Vernon Trail"),
                8: describe.RelationName("Custis Trail"),
            },
        )
        stretches = [(e["street"], e["relation_name"]) for e in entries]
        assert stretches == [
            ("Custis Trail", False),
            ("Mount Vernon Trail", True),
            ("Custis Trail", False),
        ]
        assert [e["relation_name"] for e in overview if e["kind"] == "stretch"][1] is True

    def test_an_untraced_leg_is_carried(self):
        entries, _overview = routing.describe_route(
            [(0, 1), 500.0], self.pieces()[:1], [("1", "none")], None, {"length": 0.9}
        )
        assert [e["kind"] for e in entries] == ["stretch", "via", "stretch"]
        assert entries[-1]["to_m"] == 900

    def test_no_length_leaves_the_distances_as_traced(self):
        entries, _overview = routing.describe_route(
            [(0, 2)], self.pieces(), [("1", "none")] * 2, None, {}
        )
        assert entries[-1]["to_m"] == 1000

    def test_a_failure_is_none_and_logged(self, caplog):
        entries = routing.describe_route([(0, 5)], self.pieces(), [], None, {})
        assert entries is None
        assert "could not be built" in caplog.text


@db
def test_the_street_side_names_are_read_for_unnamed_ways_only(segment_schemas):
    """v0.7.0 "Go riding fixes" item 4: `segment.sidepath_name`, for the route's ways with no
    name of their own; a named way is never looked up."""
    from django.db import connection

    from core import segment_info

    live, _staging = segment_schemas
    segment_info.forget_columns()
    with connection.cursor() as cursor:
        # Way 10 is an unnamed bicycle=use_sidepath road: its sidepath_name is the side
        # path it asks riders to use (review RL-1), never the road's own name.
        for way, name, trail in (
            (7, "9th Street Northwest protected bike lane", True),
            (8, None, True),
            (9, "X", True),
            (10, "Some Trail", False),
        ):
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, sidepath_name, is_trail_class) VALUES (%s, 0, "
                "ST_GeomFromText('LINESTRING(-77 38.9, -77 38.901)', 4326), 1, 'test', %s, %s)",
                [way, name, trail],
            )
    pieces = [
        routing.Piece(7, -77.0, 38.9, 10.0, (), "cycleway"),
        routing.Piece(8, -77.0, 38.9, 10.0, (), "cycleway"),
        routing.Piece(9, -77.0, 38.9, 10.0, ("Named Trail",), "cycleway"),
        routing.Piece(10, -77.0, 38.9, 10.0, (), "road"),
    ]
    assert routing.sidepath_names_of(pieces) == {7: "9th Street Northwest protected bike lane"}
    segment_info.forget_columns()


@db
def test_an_unnamed_way_takes_its_trail_relation_name_before_the_street_side_name(segment_schemas):
    """The owner, 2026-10-16 (the Custis Trail to the Mount Vernon Trail, said on the move): a
    way with no name of its own is named by its long trail's route relation
    (`segment.trail_name`), as a RelationName, before its street-side name (2026-10-27: the
    Metropolitan Branch Trail beside Blair Road, "why continue"). Never a national route's
    name, nor one for a named run of a quarter mile or less: those keep the street-side name."""
    from django.db import connection

    from core import segment_info

    live, _staging = segment_schemas
    segment_info.forget_columns()
    long_run = routing.RELATION_NAME_MIN_RUN_M + 1
    with connection.cursor() as cursor:
        for way, side, trail, run in (
            (7, "9th Street Northwest protected bike lane", "Some Trail", long_run),
            (8, None, "Mount Vernon Trail", long_run),
            (9, None, None, None),
            (10, None, "East Coast Greenway", long_run),
            (11, None, "US Bike Route 50", long_run),
            (12, None, "Short Trail", routing.RELATION_NAME_MIN_RUN_M),
            (13, "Blair Road Northwest bike lane", "East Coast Greenway", long_run),
            (14, "Blair Road Northwest bike lane", "Short Trail", routing.RELATION_NAME_MIN_RUN_M),
        ):
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, sidepath_name, trail_name, trail_run_m, is_trail_class) "
                "VALUES (%s, 0, "
                "ST_GeomFromText('LINESTRING(-77 38.9, -77 38.901)', 4326), 1, 'test', "
                "%s, %s, %s, true)",
                [way, side, trail, run],
            )
    pieces = [routing.Piece(w, -77.0, 38.9, 10.0, (), "cycleway") for w in range(7, 15)]
    names = routing.sidepath_names_of(pieces)
    assert names == {
        7: "Some Trail",
        8: "Mount Vernon Trail",
        13: "Blair Road Northwest bike lane",
        14: "Blair Road Northwest bike lane",
    }
    assert isinstance(names[7], describe.RelationName)
    assert isinstance(names[8], describe.RelationName)
    assert not isinstance(names[13], describe.RelationName)
    segment_info.forget_columns()


@db
@pytest.mark.usefixtures("arterial")
class TestOverviewInTheAnswer:
    def test_both_lists_are_answered_and_agree_on_a_short_route(self, client, router):
        router(named_world())
        body = post(client, good_body()).json()
        assert body["description_overview"] == body["description"]

    def test_a_short_stretch_is_merged_in_the_overview_only(self, client, router):
        fake = named_world(length_km=2.65)
        edges = fake.answers["trace_attributes"]["edges"]
        # A 350 m side street on the way: more than 300 ft, less than 0.25 mi.
        edges.insert(1, dict(edges[0], names=["Side Street"], length=0.35))
        router(fake)
        body = post(client, good_body()).json()
        streets = [e["street"] for e in body["description"] if e["kind"] == "stretch"]
        short = [e["street"] for e in body["description_overview"] if e["kind"] == "stretch"]
        assert "Side Street" in streets
        assert len(short) < len(streets)

    def test_the_schema_has_the_overview_as_an_optional_list(self):
        schema = api.RouteOut.model_json_schema()
        assert "description_overview" in schema["properties"]
        assert "description_overview" not in schema.get("required", [])
        assert api.RouteOut.model_fields["description_overview"].default is None


@db
@pytest.mark.usefixtures("arterial")
class TestTheSearchIsHandedTheRidesExposure:
    """OWNER-DECISIONS 250: the plan hands the calm search its ride's exposure
    weights and LTS 4 hold (`presets.exposure_for`): Trailmaxxing's and Cargo
    with passengers', 1, 8 and 16 with the hold and LTS 2 at a quarter (240 (A),
    FOLLOWUP-LTS2-WEIGHT); every other ride's 1, 2, 3."""

    @pytest.mark.parametrize(
        ("dials", "averse"),
        [
            ({"preset": "trailmaxxing"}, True),
            ({"preset": "cargo", "carrying": "people"}, True),
            ({"preset": "cargo", "carrying": "cargo"}, False),
            ({"preset": "default"}, False),
            ({"preset": "default", "stress": 100}, False),
            # Novice and Nervous (v0.7.0): the same weights, read a level up.
            ({"preset": "novice"}, "novice"),
            # An old Riding with kids link plans as Novice and Nervous.
            ({"preset": "kids"}, "novice"),
        ],
    )
    def test_the_plan_s_context(self, client, router, monkeypatch, dials, averse):
        from core import refine

        router(named_world())
        seen = []

        def spy(trip, ctx):
            seen.append(ctx.exposure)
            return trip, None

        monkeypatch.setattr(refine, "refine", spy)
        assert post(client, {**good_body(), **dials}).status_code == 200
        expected = presets.EXPOSURE_NOT_IN_CONTROL if averse else presets.EXPOSURE_STANDARD
        if averse == "novice":
            expected = presets.EXPOSURE_NOVICE
        assert seen == [expected]


@db
@pytest.mark.usefixtures("arterial")
class TestRollingStressFromTheTrace:
    """Review S4: each road's own routing cost, end to end (docs/stress/stress-number.md
    section 4): the trace is asked for the edge attributes, the pieces carry them, and the
    answer's rolling stress is not an estimate."""

    ATTRIBUTES = {
        "lane_count": 1,
        "cycle_lane": "none",
        "shoulder": False,
        "truck_route": False,
        "bicycle_network": 0,
        "density": 20,
        "roundabout": False,
        "surface": "paved",
    }

    def test_the_plan_prices_each_road_by_its_own_cost(self, client, router, monkeypatch):
        fake = named_world()
        for edge in fake.answers["trace_attributes"]["edges"]:
            edge.update(self.ATTRIBUTES)
        router(fake)
        seen = []
        real = routing.pieces_of_trace

        def spy(trace, shape=None):
            made = real(trace, shape)
            seen.extend(made)
            return made

        monkeypatch.setattr(routing, "pieces_of_trace", spy)
        body = post(client, good_body()).json()
        traces = [p for url, p in fake.calls if url.endswith("/trace_attributes")]
        assert traces
        for payload in traces:
            assert set(calm.TRACE_ATTRIBUTES) <= set(payload["filters"]["attributes"])
        assert seen and all(isinstance(p.road, calm.Road) for p in seen)
        assert seen[0].road.road_class == "residential" and seen[0].road.density == 20
        assert body["profile"]["calm"]["estimate"] is False

    def test_without_the_attributes_it_says_estimate(self, client, router):
        router(named_world())
        body = post(client, good_body()).json()
        assert body["profile"]["calm"]["estimate"] is True


class TestForksFromTheTrace:
    """`routing.pieces_of_trace` marks the first piece of an edge that leaves a fork
    (`describe.fork_movement`), from the other ways at the node the trace names."""

    def test_the_edge_after_a_fork_begins_with_its_movement(self):
        from test_route_api import encode_polyline6

        points = [(-76.92, 38.99), (-76.92, 38.995), (-76.925, 38.995), (-76.93, 38.995)]
        trace = {
            "units": "kilometers",
            "shape": encode_polyline6(points),
            "edges": [
                {
                    "way_id": 1,
                    "length": 0.55,
                    "begin_shape_index": 0,
                    "end_shape_index": 1,
                    "names": ["Paint Branch Trail"],
                    "begin_heading": 0,
                    "end_heading": 0,
                    # A path runs on north: the trail itself turns left.
                    "end_node": {
                        "intersecting_edges": [
                            {"begin_heading": 3, "use": "cycleway", "cyclability": "both"}
                        ]
                    },
                },
                {
                    "way_id": 2,
                    "length": 0.86,
                    "begin_shape_index": 1,
                    "end_shape_index": 3,
                    "names": ["Paint Branch Trail"],
                    "begin_heading": 270,
                    "end_heading": 270,
                },
            ],
        }
        pieces = routing.pieces_of_trace(trace)
        assert [p.fork for p in pieces] == [None, "left", None]
        # And the other ways at the node, for the ride card's junction diagram.
        assert [p.others for p in pieces] == [None, ((3.0, "cycleway", None, None),), None]

    @staticmethod
    def walk(start, *legs):
        """Points from `start` (lon, lat), each leg (compass heading, metres) on from the last."""
        import math

        points = [start]
        for heading, metres in legs:
            lon, lat = points[-1]
            north = metres * math.cos(math.radians(heading)) / 111320.0
            east = (
                metres * math.sin(math.radians(heading)) / (111320.0 * math.cos(math.radians(lat)))
            )
            points.append((lon + east, lat + north))
        return points

    def test_a_tiny_edge_at_a_junction_does_not_make_a_bend_a_left(self):
        """The owner, 2026-10-23, on Sligo Creek Trail: "Left to stay on" a gentle bend.
        A 3 m edge on from the node leans 70 degrees left; the trail bends 25, a footway
        goes off 70 left."""
        from test_route_api import encode_polyline6

        points = self.walk((-77.0, 39.0), (340, 100), (270, 3), (315, 100))
        trail = {"names": ["Sligo Creek Trail"], "use": "cycleway"}
        trace = {
            "units": "kilometers",
            "shape": encode_polyline6(points),
            "edges": [
                {
                    **trail,
                    "way_id": 1,
                    "length": 0.1,
                    "begin_shape_index": 0,
                    "end_shape_index": 1,
                    "begin_heading": 340,
                    "end_heading": 340,
                    # A footway off to the west.
                    "end_node": {
                        "intersecting_edges": [
                            {"begin_heading": 270, "use": "footway", "cyclability": "both"}
                        ]
                    },
                },
                {
                    **trail,
                    "way_id": 2,
                    "length": 0.003,
                    "begin_shape_index": 1,
                    "end_shape_index": 2,
                    "begin_heading": 270,
                    "end_heading": 270,
                },
                {
                    **trail,
                    "way_id": 3,
                    "length": 0.1,
                    "begin_shape_index": 2,
                    "end_shape_index": 3,
                    "begin_heading": 315,
                    "end_heading": 315,
                },
            ],
        }
        firsts = {p.way_id: p for p in reversed(routing.pieces_of_trace(trace))}
        # Valhalla's headings alone would make it a left at a fork.
        assert describe.fork_movement(340, 270, [(270, "footway", "both")], trail=True) == "left"
        assert firsts[2].fork is None
        assert firsts[2].turn == pytest.approx(-30, abs=5)
        assert firsts[1].turn is None

    def test_a_turnaround_reads_on_the_side_the_line_winds(self):
        from test_route_api import encode_polyline6

        # North, then a tight hairpin right round past south: the chords alone read a left.
        points = self.walk((-77.0, 39.0), (0, 100), (90, 4), (215, 100))
        trace = {
            "units": "kilometers",
            "shape": encode_polyline6(points),
            "edges": [
                {
                    "way_id": 1,
                    "length": 0.1,
                    "begin_shape_index": 0,
                    "end_shape_index": 2,
                    "begin_heading": 0,
                    "end_heading": 0,
                },
                {
                    "way_id": 2,
                    "length": 0.1,
                    "begin_shape_index": 2,
                    "end_shape_index": 3,
                    "begin_heading": 215,
                    "end_heading": 215,
                },
            ],
        }
        firsts = {p.way_id: p for p in reversed(routing.pieces_of_trace(trace))}
        assert firsts[2].turn > 180

    def test_the_ways_just_short_of_a_node_ride_on_the_edge_after_it(self):
        """A main road crossed within `describe.SHAPE_NEAR_M` before a turn: its ways
        are the turn's `prior` (the owner, 2026-10-20, on a left onto a service road)."""
        from test_route_api import encode_polyline6

        points = [(-77.0, 38.9), (-77.0, 38.9002), (-77.0, 38.9003), (-77.001, 38.9003)]

        def edge(way, km, begin, end, heading, *ways):
            node = {"end_node": {"intersecting_edges": list(ways)}} if ways else {}
            return {
                "way_id": way,
                "length": km,
                "begin_shape_index": begin,
                "end_shape_index": end,
                "begin_heading": heading,
                "end_heading": heading,
                **node,
            }

        highway = {"begin_heading": 90, "use": "road", "road_class": "primary"}
        street = {"begin_heading": 0, "use": "road", "road_class": "residential"}
        trace = {
            "units": "kilometers",
            "shape": encode_polyline6(points),
            "edges": [
                edge(1, 0.022, 0, 1, 0, highway),
                edge(2, 0.011, 1, 2, 0, street),
                edge(3, 0.08, 2, 3, 270),
            ],
        }
        firsts = {p.way_id: p for p in reversed(routing.pieces_of_trace(trace))}
        assert firsts[3].others == ((0.0, "road", "residential", None),)
        assert firsts[3].prior == ((90.0, "road", "primary", None),)
        # Past SHAPE_NEAR_M the junction is not the turn's.
        trace["edges"][1]["length"] = 0.08
        firsts = {p.way_id: p for p in reversed(routing.pieces_of_trace(trace))}
        assert firsts[3].prior is None


def traced(*edges, start=(-77.0, 39.0)):
    """A trace of `edges`, each (names, use, [(compass heading, metres), ...], the ways
    meeting the node it ends at as (heading, use, cyclability)), its line drawn from
    `start`, with Valhalla's headings taken from each edge's own first and last legs."""
    import math

    from test_route_api import encode_polyline6

    points = [start]
    out = []
    for way, (names, use, legs, ways) in enumerate(edges, 1):
        begin = len(points) - 1
        for heading, metres in legs:
            lon, lat = points[-1]
            north = metres * math.cos(math.radians(heading)) / 111320.0
            east = (
                metres * math.sin(math.radians(heading)) / (111320.0 * math.cos(math.radians(lat)))
            )
            points.append((lon + east, lat + north))
        out.append(
            {
                "way_id": way,
                "names": list(names),
                "use": use,
                "length": sum(m for _h, m in legs) / 1000.0,
                "begin_shape_index": begin,
                "end_shape_index": len(points) - 1,
                "begin_heading": legs[0][0],
                "end_heading": legs[-1][0],
                "end_node": {
                    "intersecting_edges": [
                        {"begin_heading": h, "use": u, "cyclability": c} for h, u, c in ways
                    ]
                },
            }
        )
    return {"units": "kilometers", "shape": encode_polyline6(points), "edges": out}


def said(trace):
    """The description of `trace`: each stretch's (street, the movement into it)."""
    pieces = routing.pieces_of_trace(trace)
    atoms = [
        describe.Atom(
            p.metres,
            "1",
            "path" if p.use in describe.PATH_USES else "none",
            p.names,
            p.use,
            p.heading_in,
            p.heading_out,
            fork=p.fork,
            others=p.others,
            bearing=p.bearing,
            turn=p.turn,
            choice=bool(p.choice),
        )
        for p in pieces
    ]
    return [
        (e["street"], e["turn"]["movement"] if e["turn"] else None)
        for e in describe.describe([atoms])
        if e["kind"] == "stretch"
    ]


class TestClearTurnsFromTheTrace:
    """The owner's 2026-10-23 ride, end to end from a trace's line: a clear turn along one
    trail and a turnaround are said, once, and nodes beside a turn add nothing."""

    MBT = ("Metropolitan Branch Trail",)
    PATH = ("cycleway", "both")

    def test_a_left_onto_the_trail_s_side_path_is_said(self):
        trace = traced(
            (self.MBT, "cycleway", [(0, 300)], [(90, *self.PATH)]),
            (self.MBT, "cycleway", [(265, 200)], []),
        )
        assert said(trace) == [
            ("Metropolitan Branch Trail", None),
            ("Metropolitan Branch Trail", "left"),
        ]

    def test_a_bend_where_only_a_sidewalk_meets_is_not_said(self):
        trace = traced(
            (self.MBT, "cycleway", [(0, 300)], [(90, "sidewalk", "both")]),
            (self.MBT, "cycleway", [(265, 200)], []),
        )
        assert said(trace) == [("Metropolitan Branch Trail", None)]

    def test_a_turnaround_onto_a_short_path_is_said_once(self):
        # A node 6 m on from the apex, where a footway meets, reads the turn too.
        trace = traced(
            (self.MBT, "cycleway", [(225, 300)], []),
            ((), "footway", [(30, 6)], [(300, "footway", "both")]),
            ((), "footway", [(30, 40)], [(120, "road", "both")]),
            ((), "service_road", [(110, 100)], [(20, "road", "both")]),
            (("Maple Street Northwest",), "road", [(20, 300)], []),
        )
        assert said(trace) == [
            ("Metropolitan Branch Trail", None),
            ("path", "right"),
            ("service road", "right"),
            ("Maple Street Northwest", "left"),
        ]

    def test_a_node_just_past_a_right_turn_adds_nothing(self):
        # X Street north to a T, right onto Y Street, a footway meeting Y 8 m on.
        trace = traced(
            (("X Street",), "road", [(0, 300)], [(270, "road", "both")]),
            (("Y Street",), "road", [(90, 8)], [(0, "footway", "both")]),
            (("Y Street",), "road", [(90, 300)], []),
        )
        assert said(trace) == [("X Street", None), ("Y Street", "right")]

    def test_a_node_just_short_of_a_right_turn_adds_nothing(self):
        trace = traced(
            (("X Street",), "road", [(0, 300)], [(270, *self.PATH)]),
            (("X Street",), "road", [(0, 8)], [(270, "road", "both")]),
            (("Y Street",), "road", [(90, 300)], []),
        )
        assert said(trace) == [("X Street", None), ("Y Street", "right")]

    def test_a_gentle_bend_past_a_tiny_tilted_edge_is_not_said(self):
        # Sligo Creek Trail: a 3 m edge leans 70 left, the trail bends 25, a path goes west.
        trail = ("Sligo Creek Trail",)
        trace = traced(
            (trail, "cycleway", [(340, 300)], [(270, "footway", "both"), (90, "road", "both")]),
            (trail, "cycleway", [(270, 3)], []),
            (trail, "cycleway", [(315, 300)], []),
        )
        assert said(trace) == [("Sligo Creek Trail", None)]

    def test_a_node_3_m_short_of_a_right_turn_adds_nothing(self):
        # Nearer than JUNCTION_M: the line runs on through the corner, read once, there.
        trace = traced(
            (("X Street",), "road", [(0, 300)], [(270, "footway", "both")]),
            (("X Street",), "road", [(0, 3)], [(270, "road", "both")]),
            (("Y Street",), "road", [(90, 300)], []),
        )
        assert said(trace) == [("X Street", None), ("Y Street", "right")]

    def test_a_turnaround_with_a_new_name_just_past_it_is_said_once(self):
        trace = traced(
            (("T Trail",), "cycleway", [(0, 300)], [(0, *self.PATH)]),
            (("T Trail",), "cycleway", [(170, 3)], [(90, *self.PATH)]),
            (("U Trail",), "cycleway", [(170, 300)], []),
        )
        assert said(trace) == [("T Trail", None), ("U Trail", "right")]

    def test_a_bend_where_only_a_way_back_meets_is_not_said(self):
        trace = traced(
            (self.MBT, "cycleway", [(0, 300)], [(170, *self.PATH)]),
            (self.MBT, "cycleway", [(270, 200)], []),
        )
        assert said(trace) == [("Metropolitan Branch Trail", None)]

    def test_a_sharp_turn_beside_a_spur_back_its_way_is_said(self):
        # The trail turns 100 right; a spur goes off 160 right, near the way out.
        trace = traced(
            (self.MBT, "cycleway", [(0, 300)], [(160, *self.PATH)]),
            (self.MBT, "cycleway", [(100, 200)], []),
        )
        assert said(trace) == [
            ("Metropolitan Branch Trail", None),
            ("Metropolitan Branch Trail", "right"),
        ]

    def test_nodes_under_5_m_apart_on_the_line_say_one_turn(self):
        # A left onto R Street with another node 4 m on, which the trace's lengths put
        # 6 m on: the line reads through both, so the turn is said once.
        trace = traced(
            (("17th Street path",), "cycleway", [(0, 300)], [(90, "road", "both")]),
            (("R Street Northwest",), "road", [(270, 4)], [(0, "footway", "both")]),
            (("R Street Northwest",), "road", [(270, 300)], []),
        )
        trace["edges"][1]["length"] = 0.006
        assert said(trace) == [("17th Street path", None), ("R Street Northwest", "left")]

    def test_two_turns_over_5_m_apart_on_the_line_are_each_said(self):
        # A left then a right on one trail 5.3 m apart on the line, which the trace's
        # lengths put 4.8 m apart: each is its own junction.
        trace = traced(
            (("Trail",), "cycleway", [(0, 300)], [(135, *self.PATH)]),
            (("Trail",), "cycleway", [(270, 5.3)], [(45, *self.PATH)]),
            (("Trail",), "cycleway", [(0, 300)], []),
        )
        trace["edges"][1]["length"] = 0.0048
        assert said(trace) == [("Trail", None), ("Trail", "left"), ("Trail", "right")]

    def test_two_turns_6_m_apart_are_each_said(self):
        trace = traced(
            (("Road A",), "road", [(0, 300)], [(0, "road", "both")]),
            (("Path",), "cycleway", [(270, 6)], [(270, "road", "both")]),
            (("Path B",), "cycleway", [(0, 300)], []),
        )
        assert said(trace) == [("Road A", None), ("Path", "left"), ("Path B", "right")]


class TestRetraces:
    """Round-3 audit D31: a turnaround on the way itself is read from the trace's own line:
    the same way, and back over the points it came in on (`Piece.retrace`)."""

    LAT = 38.99
    NORTH = 1 / 111_195  # a metre north, in degrees

    def point(self, north_m, east_m=0.0):
        east = east_m / (111_195 * 0.777)
        return (-77.02 + east, self.LAT + north_m * self.NORTH)

    def trace(self, shape, back_way=7):
        return {
            "units": "kilometers",
            "shape": encode_polyline6(shape),
            "edges": [
                {"way_id": 7, "begin_shape_index": 0, "end_shape_index": 2, "length": 0.3},
                {"way_id": back_way, "begin_shape_index": 2, "end_shape_index": 4, "length": 0.3},
            ],
        }

    def test_a_dead_end_out_and_back_is_a_retrace(self):
        shape = [self.point(0), self.point(150), self.point(300), self.point(150), self.point(0)]
        pieces = routing.pieces_of_trace(self.trace(shape))
        flagged = [p for p in pieces if p.retrace]
        assert len(flagged) == 1 and abs(flagged[0].turn) >= describe.UTURN_DEG

    def test_a_leg_begun_part_way_along_still_retraces(self):
        # In from 40 m short of the dead end; back out along the whole way.
        shape = [self.point(260), self.point(280), self.point(300), self.point(150), self.point(0)]
        assert any(p.retrace for p in routing.pieces_of_trace(self.trace(shape)))

    def test_a_switchback_is_not_a_retrace(self):
        # Back on a parallel line 6 m to the side: a hairpin bend, not the same points.
        shape = [
            self.point(0),
            self.point(150),
            self.point(300),
            self.point(150, 6),
            self.point(0, 6),
        ]
        assert not any(p.retrace for p in routing.pieces_of_trace(self.trace(shape)))

    def test_back_on_another_way_is_not_a_retrace(self):
        shape = [self.point(0), self.point(150), self.point(300), self.point(150), self.point(0)]
        assert not any(p.retrace for p in routing.pieces_of_trace(self.trace(shape, 8)))

    def test_a_u_turn_entry_is_in_the_contract(self):
        out = [describe.Atom(300.0, "1", "path", ("A Trail",), "cycleway", 0.0, 0.0)]
        back = describe.Atom(
            300.0, "1", "path", ("A Trail",), "cycleway", 180.0, 180.0, turn=180.0, retrace=True
        )
        entry = describe.describe([[*out, back]])[1]
        turn = api.DescriptionEntryOut.model_validate(entry).model_dump()["turn"]
        assert turn["movement"] == "uturn"
