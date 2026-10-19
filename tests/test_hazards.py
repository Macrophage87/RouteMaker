"""v0.10.0's hazard symbols: the kinds from tags and street rails (`routemaker.hazards`,
`pipeline.hazard_layer`), the reviewed list (`fixtures/hazards/`), the graph's price, the
route's marks and the road panel.

The owner, 2026-10-19: "We should have a symbol for roads with known other hazards on the
map. One example is the cobblestones in Georgetown or the streetcar rails on H street".
Then: "Roads with hazards like this should get a major penalty. You only need to show it
if it's routed on". A hazard never changes a way's stress rating; the graph prices it.
"""

from __future__ import annotations

import json

import pytest

from routemaker import hazards

# An east-west street, about 860 m [0.5 mi], and two cross streets meeting it.
STREET = [(-77.070 + i * 0.001, 38.908) for i in range(11)]


def _way(osm_id, coords, node_ids=None, **tags):
    from pipeline.extract import Way

    return Way(
        osm_id,
        {"highway": "residential", **tags},
        node_ids if node_ids is not None else [osm_id * 100 + i for i in range(len(coords))],
        coords,
    )


# --- the kinds -------------------------------------------------------------------------


@pytest.mark.parametrize("surface", ["sett", "cobblestone", "unhewn_cobblestone"])
def test_a_cobbled_surface_is_cobbles(surface):
    assert hazards.way_kinds({"surface": surface}) == {hazards.COBBLES}


@pytest.mark.parametrize("surface", ["asphalt", "paving_stones", "brick", ""])
def test_other_surfaces_are_not(surface):
    assert hazards.way_kinds({"surface": surface}) == set()


def test_embedded_rails_on_the_road_is_rails():
    assert hazards.way_kinds({"embedded_rails": "tram"}) == {hazards.RAILS}
    assert hazards.way_kinds({"embedded_rails": "no"}) == set()


@pytest.mark.parametrize(
    ("tags", "street"),
    [
        ({"railway": "tram"}, True),
        ({"railway": "light_rail", "embedded": "yes"}, True),
        ({"railway": "light_rail"}, False),
        ({"railway": "rail"}, False),
        ({"railway": "disused", "disused:railway": "tram"}, True),
        ({"railway": "disused"}, False),
        ({"railway": "abandoned", "embedded": "yes"}, False),
        ({"highway": "residential"}, False),
    ],
)
def test_which_railways_are_in_the_street(tags, street):
    assert hazards.is_street_rail(tags) is street


def test_the_column_round_trips_and_credits_its_source():
    text = hazards.encode({hazards.RAILS}, {hazards.COBBLES, hazards.RAILS})
    assert text == "cobbles/list,rails"
    assert hazards.decode(text) == [("cobbles", True), ("rails", False)]
    assert hazards.words(text).startswith("Cobblestones")
    assert hazards.credits(text) == "OpenStreetMap and RouteMaker's hazard list"
    assert hazards.encode((), ()) is None
    assert hazards.words(None) is None and hazards.words("unknown") is None


# --- the reviewed list -----------------------------------------------------------------


def test_the_shipped_list_loads():
    entries = hazards.load()
    ids = {e.id for e in entries}
    assert "georgetown-o-street-wisconsin-to-35th" in ids
    assert "h-street-ne-streetcar-rails" in ids
    assert all(e.source.startswith(("The owner", "As ")) for e in entries)


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "a", "kinds": ["potholes"], "ways": [1], "source": "x"},
        {"id": "a", "kinds": ["rails"], "ways": [1], "source": " "},
        {"id": "a", "kinds": ["rails"], "street": "X Street", "source": "x"},
        {"id": "a", "kinds": ["rails"], "source": "x"},
        {"id": "a", "kinds": "rails", "ways": ["seven"], "source": "x"},
    ],
)
def test_a_bad_entry_is_refused(entry):
    with pytest.raises(hazards.HazardListRefused):
        hazards.parse({"hazards": [entry]})


def test_a_missing_folder_and_duplicate_ids_are_refused(tmp_path):
    with pytest.raises(hazards.HazardListRefused):
        hazards.load(tmp_path / "absent")
    entry = {"id": "a", "kinds": ["rails"], "ways": [1], "source": "x"}
    for name in ("1.json", "2.json"):
        (tmp_path / name).write_text(json.dumps({"hazards": [entry]}))
    with pytest.raises(hazards.HazardListRefused):
        hazards.load(tmp_path)


def test_a_street_is_marked_between_its_cross_streets_only():
    from pipeline import hazard_layer

    street = _way(1, STREET, name="O Street Northwest")
    # Cross streets at the street's third and seventh nodes, sharing those nodes.
    west = _way(2, [(-77.068, 38.907), STREET[2]], [200, street.node_ids[2]], name="West St")
    east = _way(3, [STREET[6], (-77.064, 38.909)], [street.node_ids[6], 301], name="East St")
    entry = hazards.ListedHazard(
        "o", (hazards.COBBLES,), "x", street="O Street Northwest", between=("West St", "East St")
    )
    listed = hazard_layer.listed_by_way([street, west, east], [entry])
    assert set(listed) == {1}
    tags = street.tags
    inside = [STREET[3], STREET[4]]
    outside = [STREET[8], STREET[9]]
    assert hazard_layer.piece_hazard(tags, False, listed[1], inside) == "cobbles/list"
    assert hazard_layer.piece_hazard(tags, False, listed[1], outside) is None


def test_a_cross_street_not_found_is_left_out(caplog):
    from pipeline import hazard_layer

    street = _way(1, STREET, name="O Street Northwest")
    entry = hazards.ListedHazard(
        "o", (hazards.RAILS,), "x", street="O Street Northwest", between=("Nowhere", "Else")
    )
    assert hazard_layer.listed_by_way([street], [entry]) == {}
    assert "not found" in caplog.text


def test_a_tram_line_along_a_road_marks_it_and_not_a_cross_street_or_alley():
    from pipeline import hazard_layer

    road = _way(1, STREET, name="H Street Northeast")
    alley = _way(4, [(x, y + 0.00005) for x, y in STREET], highway="service")
    cross = _way(5, [(-77.065, 38.905), (-77.065, 38.911)], name="Cross Street")
    rail = (900, [(x, y + 0.00003) for x, y in STREET])
    assert hazard_layer.rail_ways([road, alley, cross], [rail]) == {1}
    assert hazard_layer.piece_hazard(road.tags, True, (), STREET[:3]) == "rails"


def test_the_rails_are_read_from_the_extract(tmp_path):
    from pipeline.hazard_layer import read_rails

    osm = tmp_path / "rails.osm"
    osm.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" version="1" lat="38.9" lon="-77.0"/>
  <node id="2" version="1" lat="38.9" lon="-76.99"/>
  <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="railway" v="tram"/></way>
  <way id="11" version="1"><nd ref="1"/><nd ref="2"/><tag k="railway" v="rail"/></way>
</osm>
"""
    )
    assert read_rails(osm) == [(10, [(-77.0, 38.9), (-76.99, 38.9)])]


def test_a_hazard_is_never_a_stress_input():
    from routemaker.stress import classify

    tags = {"highway": "residential", "maxspeed": "25 mph", "surface": "sett"}
    assert classify({**tags, "embedded_rails": "tram"}).tier == classify(tags).tier


# --- the tiles and the road panel ------------------------------------------------------


def test_the_tiles_do_not_carry_hazards():
    """Shown only on a route that rides one (the owner, 2026-10-19), never on the whole map."""
    from core import stress_tiles
    from pipeline.schema import HAZARD_COLUMN

    assert HAZARD_COLUMN not in stress_tiles.OPTIONAL_PROPERTIES.values()


def test_the_graph_is_told_of_a_hazard_anywhere_on_the_way():
    from pipeline import hazard_layer

    street = _way(1, STREET, name="O Street Northwest")
    assert not hazard_layer.way_has_hazard(street, False, ())
    assert hazard_layer.way_has_hazard(street, True, ())
    assert hazard_layer.way_has_hazard(_way(2, STREET, surface="sett"), False, ())
    stretch = hazard_layer.Stretch(STREET[3], STREET[4])
    assert hazard_layer.way_has_hazard(street, False, [(stretch, (hazards.RAILS,))])
    far = hazard_layer.Stretch((-76.0, 39.0), (-75.9, 39.0))
    assert not hazard_layer.way_has_hazard(street, False, [(far, (hazards.RAILS,))])


def test_the_blocks_beyond_the_junctions_are_neither_marked_nor_priced():
    """A way that only leaves a junction outward is not on the stretch, however short."""
    from pipeline import extract, hazard_layer

    stretch = hazard_layer.Stretch(STREET[2], STREET[6])
    listed = [(stretch, (hazards.COBBLES,))]
    for coords in ([STREET[6], STREET[7]], STREET[6:], [STREET[1], STREET[2]], STREET[:3]):
        beyond = _way(7, coords, name="O Street Northwest")
        assert not hazard_layer.way_has_hazard(beyond, False, listed), coords
        for _, piece in extract.iter_segments(beyond):
            assert hazard_layer.piece_hazard(beyond.tags, False, listed, piece) is None
    block = _way(8, STREET[2:7], name="O Street Northwest")
    assert hazard_layer.way_has_hazard(block, False, listed)
    # A short piece wholly on the stretch is marked too.
    assert hazard_layer.piece_hazard(
        {}, False, listed, [STREET[3], (STREET[3][0] + 0.0001, STREET[3][1])]
    )


def _piece(way_id, metres, name=None):
    from core.routing import Piece

    return Piece(way_id, -77.0, 38.9, metres, names=(name,) if name else ())


def test_the_route_says_each_hazard_stretch_once_in_riding_order():
    from core import route_hazards

    pieces = [
        _piece(1, 100.0, "Quiet Street"),
        _piece(2, 50.0, "H Street Northeast"),
        _piece(2, 70.0, "H Street Northeast"),
        _piece(3, 200.0, "Quiet Street"),
        _piece(4, 30.0, "O Street Northwest"),
    ]
    kinds = [(), ("rails",), ("rails",), (), ("cobbles", "rails")]
    found = route_hazards.along([(0, 5)], pieces, kinds)
    assert [(f["from_m"], f["to_m"], f["kinds"], f["road"]) for f in found] == [
        (100, 220, ["rails"], "H Street Northeast"),
        (420, 450, ["cobbles", "rails"], "O Street Northwest"),
    ]
    assert found[0]["text"] == (
        "Rails in the road on H Street Northeast, 0.1 to 0.1 mi (0.1 to 0.2 km): "
        "cross them square on, a wheel can drop into the groove."
    )
    assert found[1]["text"].startswith("Cobblestones and rails in the road on O Street")
    assert route_hazards.along([(0, 5)], pieces, [()] * 5) == []


def test_a_walk_between_legs_counts_toward_the_distance():
    from core import route_hazards

    pieces = [_piece(1, 100.0), _piece(2, 100.0)]
    found = route_hazards.along([(0, 1), 500.0, (1, 2)], pieces, [(), ("cobbles",)])
    assert (found[0]["from_m"], found[0]["to_m"], found[0]["road"]) == (600, 700, "an unnamed road")


def test_the_hazards_go_in_the_directions_in_place():
    from core import route_hazards

    found = [{"from_m": 150, "to_m": 200, "kinds": ["rails"], "road": "H Street", "text": "t"}]
    description = [{"kind": "stretch", "from_m": 0}, {"kind": "stretch", "from_m": 150}]
    out = route_hazards.with_entries(description, found)
    assert [e["kind"] for e in out] == ["stretch", "hazard", "stretch"]
    assert out[1]["street"] == "H Street" and out[1]["text"] == "t"
    assert route_hazards.with_entries(None, found) is None


def test_no_hazard_column_no_hazards(monkeypatch):
    from core import route_hazards, segment_info

    monkeypatch.setattr(segment_info, "has_columns", lambda *a: False)
    assert route_hazards.kinds_of([_piece(1, 10.0)]) == [()]


def _row(**extra) -> dict:
    return {
        "osm_way_id": 42,
        "stress_tier": 2,
        "stress_rule": "",
        "stress_assumed": [],
        "volume_source": None,
        "volume_aadt": None,
        "volume_year": None,
        "is_trail_class": False,
        "is_unpaved": False,
        "is_rough": False,
        "distance_m": 1.0,
        "on_lon": -77.06,
        "on_lat": 38.9,
        **extra,
    }


def test_the_road_panel_says_the_hazard_in_words():
    from core import segment_info

    row = _row(hazard="cobbles,rails/list")
    summary = segment_info.summary_rows(row, {}, True)
    watch = next(r for r in summary if r["id"] == "hazard")
    assert watch["label"] == "Watch for" and "Cobblestones" in watch["value"]
    assert "Rails in the road" in watch["value"]
    riding = segment_info.riding_rows(row)
    assert any(r["label"] == "Watch for" and "RouteMaker" in r["source"] for r in riding)
    assert not any(r["id"] == "hazard" for r in segment_info.summary_rows(_row(), {}, True))


def test_the_calm_search_reads_a_hazard_as_lts_4_and_shows_its_own_rating():
    from core import refine, routing

    classes = [
        routing.PieceClass("1", "none"),
        routing.PieceClass("2", "path"),
        routing.PieceClass("3", "lane", half=True),
        routing.PieceClass("4", "none"),
    ]
    kinds = [(hazards.COBBLES,), (hazards.RAILS,), (hazards.RAILS,), (hazards.RAILS,)]
    priced = refine.hazard_priced(classes, kinds)
    assert [(c[0], getattr(c, "half", False)) for c in priced] == [
        ("4", False),
        ("2", False),  # a path is never priced, as the graph never prices a trail
        ("4", False),
        ("4", False),
    ]
    assert refine.hazard_priced(classes, [()] * 4) is classes


def test_a_short_stretch_is_said_at_one_place_and_a_walk_is_never_joined_across():
    from core import route_hazards

    pieces = [_piece(2, 10.0, "H Street Northeast"), _piece(2, 10.0, "H Street Northeast")]
    found = route_hazards.along([(0, 1), 5.0, (1, 2)], pieces, [("rails",), ("rails",)])
    assert [(f["from_m"], f["to_m"]) for f in found] == [(0, 10), (15, 25)]
    assert found[0]["text"].startswith(
        "Rails in the road on H Street Northeast, at 0.0 mi (0.0 km): "
    )
