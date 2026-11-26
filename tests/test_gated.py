"""Streets behind a closed gate are private (`routemaker.gated`; the owner, 2026-11-25:
"a lot of roads that are in housing complexes only open to people who are residents or
guests")."""

from __future__ import annotations

from routemaker import gated

GATE = 10


def _network(gate_tags: dict | None = None):
    # A county road (1-2-3), a community entrance (3-10-4) with the gate at node 10, and
    # the community's loop behind it (4-5-6-4) with a cul-de-sac (5-7).
    ways = [
        (100, {"highway": "tertiary"}, [1, 2, 3]),
        (101, {"highway": "residential", "name": "Entry Dr"}, [3, GATE, 4]),
        (102, {"highway": "residential"}, [4, 5, 6, 4]),
        (103, {"highway": "residential"}, [5, 7]),
        (104, {"highway": "footway"}, [7, 2]),  # a footpath out to the county road
    ]
    closed = gated.is_closed_gate(gate_tags or {"barrier": "gate", "access": "private"})
    gates = {GATE} if closed else set()
    return ways, gates


def test_a_closed_gate_is_read_from_its_tags() -> None:
    assert gated.is_closed_gate({"barrier": "gate", "access": "private"})
    assert gated.is_closed_gate({"barrier": "lift_gate", "motor_vehicle": "residents"})
    assert not gated.is_closed_gate({"barrier": "gate"})  # a plain gate says nothing
    assert not gated.is_closed_gate({"barrier": "gate", "access": "private", "bicycle": "yes"})
    assert not gated.is_closed_gate({"barrier": "bollard", "access": "no"})


def test_the_streets_behind_the_gate_are_closed_and_the_road_outside_is_not() -> None:
    ways, gates = _network()
    # The entrance runs through the gate to the county road: left as it is.
    assert gated.behind_gates(ways, gates) == {102, 103}


def test_a_street_joined_to_the_network_without_a_gate_stays_open() -> None:
    ways, gates = _network()
    ways.append((105, {"highway": "residential"}, [6, 1]))  # a second, ungated entrance
    assert gated.behind_gates(ways, gates) == set()


def test_a_plain_gate_or_a_street_with_its_own_tags_stays_open() -> None:
    ways, gates = _network({"barrier": "gate"})
    assert gated.behind_gates(ways, gates) == set()
    ways, gates = _network()
    ways[2] = (102, {"highway": "residential", "access": "destination"}, [4, 5, 6, 4])
    assert gated.behind_gates(ways, gates) == {103}


def test_an_entrance_drive_tagged_private_closes_the_streets_behind_it() -> None:
    ways, _ = _network({"barrier": "gate"})
    ways[1] = (101, {"highway": "residential", "access": "private"}, [3, GATE, 4])
    assert gated.behind_gates(ways, set()) == {102, 103}


def test_a_private_driveway_off_a_public_street_closes_nothing() -> None:
    ways = [
        (100, {"highway": "tertiary"}, [1, 2]),
        (101, {"highway": "residential"}, [2, 3, 4]),  # a public dead-end street
        (102, {"highway": "service", "access": "private"}, [3, 30]),  # a driveway off it
    ]
    assert gated.behind_gates(ways, set()) == set()


def test_a_street_behind_a_gate_is_closed_after_the_area_rules_and_worded_for_the_panel() -> None:
    from core import segment_info
    from core.routing import NOT_PUBLIC_REASONS
    from pipeline import trail_closures as tc
    from pipeline.extract import Way

    assert tc.ORDER.index(gated.NO_BICYCLE) == tc.ORDER.index("track") + 1
    line = [(-81.80, 26.30), (-81.79, 26.30)]
    ways = [
        Way(osm_id=i, tags={"highway": "residential"}, node_ids=[1, 2], coordinates=line)
        for i in (1, 2, 3)
    ]
    nobike = tc.closures(ways, {}, [], tracks={1}, behind_gates={1, 2})
    assert nobike.reasons == {1: "track", 2: gated.NO_BICYCLE}
    is_open, words = segment_info.ACCESS_WORDS[gated.NO_BICYCLE]
    assert not is_open and "gate" in words
    assert segment_info.ACCESS_SHORT[gated.NO_BICYCLE] == "gated community"
    # A destination on one gets the not-public end note.
    assert gated.NO_BICYCLE in NOT_PUBLIC_REASONS


def test_a_communitys_own_paths_are_private_like_its_streets() -> None:
    ways, gates = _network()
    behind = gated.behind_gates(ways, gates)
    ways += [
        # Bonita Bay's: the residents' bike path, tagged private and designated.
        (200, {"highway": "cycleway", "access": "private", "bicycle": "designated"}, [5, 20]),
        (201, {"highway": "path", "access": "private", "bicycle": "permissive"}, [5, 21]),
        # An untagged loop met only by the community's streets.
        (202, {"highway": "path"}, [6, 22, 23]),
        # An untagged path from the community out to the county road: public.
        (203, {"highway": "footway"}, [4, 24, 2]),
        # A path alone in a park, met by no street: left as it is.
        (204, {"highway": "path"}, [30, 31]),
    ]
    # The footpath 104 (7-2) joins the community to the county road too.
    assert gated.private_paths(ways, behind) == {200, 202}
