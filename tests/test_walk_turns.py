"""Turn-by-turn on foot (Stephen, 2026-11-02): a walk's turns from the router's maneuvers."""

from core import walk_turns

SHAPE = [(-77.0, 38.9), (-77.0, 38.901), (-77.001, 38.901), (-77.001, 38.9012), (-77.002, 38.9012)]


def _leg(*maneuvers) -> dict:
    return {"maneuvers": list(maneuvers)}


def test_turns_carry_the_movement_the_street_and_the_point() -> None:
    leg = _leg(
        {"type": 2, "begin_shape_index": 0, "length": 0.1, "street_names": ["1st St NE"]},
        {"type": 15, "begin_shape_index": 1, "length": 0.09, "street_names": ["F St NE"]},
        {"type": 9, "begin_shape_index": 3, "length": 0.09, "street_names": ["3rd St NE"]},
        {"type": 4, "begin_shape_index": 4, "length": 0.0},
    )
    assert walk_turns.turns_of(leg, SHAPE) == [
        {"movement": "left", "street": "F St NE", "point": [-77.0, 38.901]},
        {"movement": "bear_right", "street": "3rd St NE", "point": [-77.001, 38.9012]},
    ]


def test_an_unnamed_crosswalk_jog_is_not_said_but_a_long_unnamed_path_is() -> None:
    leg = _leg(
        {"type": 10, "begin_shape_index": 1, "length": 0.012},  # onto the crosswalk
        {"type": 14, "begin_shape_index": 2, "length": 0.2},  # onto a path, a long way
    )
    assert walk_turns.turns_of(leg, SHAPE) == [
        {"movement": "left", "street": None, "point": [-77.001, 38.901]}
    ]


def test_no_maneuvers_and_bad_indices_give_no_turns() -> None:
    assert walk_turns.turns_of({}, SHAPE) == []
    leg = _leg({"type": 10, "begin_shape_index": 99, "length": 1, "street_names": ["A St"]})
    assert walk_turns.turns_of(leg, SHAPE) == []


def test_the_request_asks_for_maneuvers() -> None:
    assert walk_turns.directions({"directions_type": "none"})["directions_type"] == "maneuvers"
