"""State polygons from the extract's own boundaries, and each way's state
(pipeline.states; OWNER-DECISIONS 137: "From our OSM data (Recommended)")."""

from __future__ import annotations

from types import SimpleNamespace

import osmium
import pytest
from rebuild_fixtures import STATE_BOXES, add_state_boundaries

from pipeline import states

db = pytest.mark.django_db


def empty_extract(path):
    writer = osmium.SimpleWriter(str(path))
    writer.add_node(osmium.osm.mutable.Node(id=1, location=(-77.05, 38.90), tags={}, version=1))
    writer.close()


@pytest.fixture
def boundaries(tmp_path):
    source = tmp_path / "empty.osm.pbf"
    empty_extract(source)
    merged = tmp_path / "merged.osm.pbf"
    add_state_boundaries(source, merged)
    return merged


def way(osm_id, *coords):
    return SimpleNamespace(osm_id=osm_id, tags={}, coordinates=list(coords))


class TestRings:
    def test_member_ways_join_end_to_end_either_way_round(self) -> None:
        closed, dropped = states.rings([[1, 2, 3], [5, 4, 3], [5, 6, 1]])
        assert dropped == 0
        assert len(closed) == 1 and set(closed[0]) == {1, 2, 3, 4, 5, 6}
        assert closed[0][0] == closed[0][-1]

    def test_an_open_chain_is_dropped(self) -> None:
        # A relation cut by an extract: the ring never closes.
        assert states.rings([[1, 2, 3], [3, 4]]) == ([], 1)

    def test_two_rings(self) -> None:
        closed, dropped = states.rings([[1, 2, 3, 1], [7, 8, 9], [9, 7]])
        assert (len(closed), dropped) == (2, 0)


def test_the_extracts_boundaries_become_one_polygon_a_state(boundaries) -> None:
    polygons = states.state_polygons(boundaries)
    assert set(polygons) == set(STATE_BOXES)
    west, east, south, north = STATE_BOXES["DC"]
    assert polygons["DC"].extent == pytest.approx((west, south, east, north))


def test_a_relation_without_a_state_code_is_ignored(tmp_path) -> None:
    source = tmp_path / "e.osm.pbf"
    empty_extract(source)
    add_state_boundaries(source, source, {"XX": (-1.0, 1.0, -1.0, 1.0)})
    assert set(states.state_polygons(source)) == {"XX"}
    assert states._state_code({"ISO3166-2": "GB-ENG"}) is None
    assert states._state_code({"ISO3166-2": "US-dc"}) == "DC"
    assert states._state_code({"ISO3166-2": "US-DC-001"}) is None


def test_an_inner_ring_is_a_hole(tmp_path) -> None:
    path = tmp_path / "hole.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    square = {
        1: (0.0, 0.0),
        2: (4.0, 0.0),
        3: (4.0, 4.0),
        4: (0.0, 4.0),
        5: (1.0, 1.0),
        6: (2.0, 1.0),
        7: (2.0, 2.0),
        8: (1.0, 2.0),
    }
    for node_id, location in square.items():
        writer.add_node(osmium.osm.mutable.Node(id=node_id, location=location, tags={}, version=1))
    writer.add_way(osmium.osm.mutable.Way(id=1, nodes=[1, 2, 3, 4, 1], tags={}, version=1))
    writer.add_way(osmium.osm.mutable.Way(id=2, nodes=[5, 6, 7, 8, 5], tags={}, version=1))
    tags = {"boundary": "administrative", "admin_level": "4", "ISO3166-2": "US-DC"}
    writer.add_relation(
        osmium.osm.mutable.Relation(
            id=1, members=[("w", 1, "outer"), ("w", 2, "inner")], tags=tags, version=1
        )
    )
    writer.close()
    dc = states.state_polygons(path)["DC"]
    assert dc.area == pytest.approx(16.0 - 1.0)


@db
class TestWayStates:
    def test_each_way_takes_the_state_its_middle_vertex_is_in(self, boundaries) -> None:
        polygons = states.state_polygons(boundaries)
        ways = [
            way(1, (-77.05, 38.90), (-77.04, 38.90), (-77.03, 38.90)),  # the District
            way(2, (-76.95, 38.90), (-76.94, 38.90)),  # Virginia
            way(3, (-77.05, 39.00), (-77.04, 39.00)),  # Maryland
            way(4, (-76.50, 38.00), (-76.40, 38.00)),  # in no state
            way(5),  # no geometry
        ]
        placed = states.way_states(ways, polygons, required=("DC", "MD", "VA"))
        assert placed == {1: "DC", 2: "VA", 3: "MD"}

    def test_a_vertex_on_a_shared_boundary_takes_the_higher_default(self, boundaries) -> None:
        """Western and Eastern Avenues and Southern Avenue run on the District
        line; a middle vertex on it goes to Maryland (or Virginia), whose
        default is the higher reading."""
        polygons = states.state_polygons(boundaries)
        on_dc_va = way(1, (-77.00, 38.89), (-77.00, 38.90), (-77.00, 38.91))
        on_dc_md = way(2, (-77.06, 38.95), (-77.05, 38.95), (-77.04, 38.95))
        inside = way(3, (-77.05, 38.90), (-77.04, 38.90))
        placed = states.way_states([on_dc_va, on_dc_md, inside], polygons, required=("DC",))
        assert placed == {1: "VA", 2: "MD", 3: "DC"}

    def test_a_missing_required_state_refuses(self, boundaries) -> None:
        polygons = states.state_polygons(boundaries)
        del polygons["MD"]
        with pytest.raises(states.StatesMissing, match="no state polygon for MD"):
            states.way_states([way(1, (-77.05, 38.90))], polygons, required=("DC", "MD", "VA"))

    def test_a_required_state_holding_no_way_refuses(self, boundaries) -> None:
        polygons = states.state_polygons(boundaries)
        with pytest.raises(states.StatesMissing, match="no way placed in MD"):
            states.way_states(
                [way(1, (-77.05, 38.90)), way(2, (-76.95, 38.90))],
                polygons,
                required=("DC", "MD", "VA"),
            )

    def test_the_real_list_is_the_coverages_three(self) -> None:
        assert states.STATE_PRIORITY.index("DC") == len(states.STATE_PRIORITY) - 1
        assert {"DC", "MD", "VA"} <= set(states.STATE_PRIORITY)

    def test_chunks_cover_every_way(self, boundaries, monkeypatch) -> None:
        monkeypatch.setattr(states, "CHUNK", 2)
        polygons = states.state_polygons(boundaries)
        ways = [way(i, (-77.05 + i * 0.001, 38.90)) for i in range(7)]
        assert set(states.way_states(ways, polygons, required=("DC",))) == set(range(7))
