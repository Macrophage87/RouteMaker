"""Every movement the route description can say passes the route response schema.

v0.7.0 added bears to `describe` but not to `DescriptionTurnOut`, so /api/route
answered 500 on any route with a bear (2026-10-16)."""

from __future__ import annotations

from test_describe import flat, road

from core.api import DescriptionEntryOut, DescriptionTurnOut
from routemaker import describe as d


def test_the_schema_allows_every_movement_describe_says():
    for movement in [*d.TURN_WORDS, "straight", None]:
        DescriptionTurnOut.model_validate(
            {"movement": movement, "onto": None, "control": None, "severity": None}
        )


def test_a_route_with_bears_validates_as_a_response():
    legs = [
        flat(
            road("Main St", 1, 600, 0, 0),
            road("Fork Rd", 1, 600, 328, 328),
            road("Q Street Northwest", 2, 900, 0, 0),
            road("Rhode Island Avenue Northwest", 2, 1300, 35, 35),
        )
    ]
    entries = d.describe(legs)
    movements = {e["turn"]["movement"] for e in entries if e["turn"]}
    assert {"bear_left", "bear_right"} <= movements
    for entry in entries:
        DescriptionEntryOut.model_validate(entry)


def test_the_way_an_unnamed_path_leads_to_reaches_the_response():
    """D21: the `toward` field is the response's, not dropped by the schema."""
    legs = [
        flat(
            road("Capital Crescent Trail", 1, 1500, 90, 90, "path", "cycleway"),
            road("", 1, 150, 180, 180, "path", "cycleway"),
            road("Rock Creek Trail", 1, 1500, 90, 90, "path", "cycleway"),
        )
    ]
    entry = d.describe(legs)[1]
    out = DescriptionEntryOut.model_validate(entry).model_dump()
    assert out["turn"]["toward"] == "Rock Creek Trail"
    assert out["turn"]["onto"] == out["street"] == "path"
