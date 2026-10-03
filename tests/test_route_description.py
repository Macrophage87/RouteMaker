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
from routemaker import describe

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
        assert stretch["tier"] == 2 and stretch["facility"] is None
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

    def test_a_street_change_is_a_turn_with_its_signal(self, client, router):
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

    @pytest.mark.parametrize("preset", sorted(presets.PRESETS))
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
            "text",
        }
        assert entry["properties"]["kind"]["enum"] == ["stretch", "junction", "via"]
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
        assert [e["facility"] for e in entries] == [None, "path"]
        assert entries[1]["turn"]["movement"] == "left"
        assert entries[-1]["to_m"] == 1000

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
