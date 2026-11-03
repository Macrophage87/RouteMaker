"""A sidewalk or shared path named for its street at the rebuild ("sidewalk beside Kemp
Mill Road"; `routemaker.facility.sidepath_name`) is never called a bike lane. The owner,
2026-11-03: "Kemp Mill road doesn't have a bike lane" and "There's a narrow sidewalk
which I wouldn't call a "path"."""

from __future__ import annotations

from routemaker import describe as d
from tests.test_describe import flat, road


def _row(**extra) -> dict:
    return {
        "osm_way_id": 886775743,
        "stress_tier": 1,
        "stress_rule": "",
        "stress_assumed": [],
        "volume_source": None,
        "volume_aadt": None,
        "volume_year": None,
        "is_trail_class": True,
        "is_unpaved": False,
        "is_rough": False,
        "distance_m": 1.0,
        "on_lon": -77.03,
        "on_lat": 39.06,
        "facility": "protected",
        **extra,
    }


def test_the_cue_does_not_call_the_sidewalk_a_bike_lane() -> None:
    entries = d.describe(
        [
            flat(
                road("Arcola Avenue", 2, 400, 0, 0),
                road("sidewalk beside Kemp Mill Road", 1, 600, 90, 90, "protected", "footway"),
            )
        ]
    )
    text = entries[1]["text"]
    assert "the sidewalk beside Kemp Mill Road" in text
    assert "bike lane" not in text
    assert "low stress (LTS 1)" in text


def test_the_road_panel_does_not_say_bike_lane_beside_a_sidewalk_name() -> None:
    from core import segment_info

    rows = segment_info.summary_rows(_row(sidepath_name="sidewalk beside Kemp Mill Road"), {}, True)
    assert not any(r["id"] == "bike_lane" for r in rows)
    # A protected way with no such name still says it.
    rows = segment_info.summary_rows(_row(sidepath_name=None), {}, True)
    assert any(r["id"] == "bike_lane" and r["value"] == "Protected" for r in rows)
