"""What the connector says of a trail ride (routing hunt 4): a Mountain Bike route's trail
reading (M4-1), a route past the rider's target distance (M4-3), and mountain-bike trails
said as trail rather than as ordinary street (M4-4). mcp/routemaker_mcp.py, on answers
built by hand: no site, no map."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if "routemaker_mcp" in sys.modules:
    mcp = sys.modules["routemaker_mcp"]
else:
    _spec = importlib.util.spec_from_file_location(
        "routemaker_mcp", Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
    )
    mcp = importlib.util.module_from_spec(_spec)
    sys.modules["routemaker_mcp"] = mcp
    _spec.loader.exec_module(mcp)

MI = mcp.METRES_PER_MILE
START = (-77.31, 39.14)
LON_MI = 1 / 53.7


def reading(**figures) -> dict:
    """An answer's `mtb` (core/mtb.py `figures` and `settle`'s own keys)."""
    return {
        "max_level": 2,
        "preferred_level": None,
        "limited": None,
        "trail_m": 0.0,
        "singletrack_m": 0.0,
        "over_level_m": 0.0,
        "long_lts3_m": 0.0,
        "lts4_m": 0.0,
        "easier_m": 0.0,
        "harder_m": 0.0,
        **figures,
    }


# --- M4-1: the Mountain Bike trail reading ---------------------------------------------------


def test_a_route_with_no_trail_says_so_with_its_road_warnings() -> None:
    # Lake Frank, level 4: a road route, 0.55 mi of LTS 3 in a long run and a little LTS 4.
    said = mcp.mtb_said(reading(max_level=4, long_lts3_m=0.55 * MI, lts4_m=32.0))
    assert said == [
        "It uses 0.0 mi (0.0 km) of busy road (LTS 4 or Avoid): no calmer connection was found.",
        "It has 0.6 mi (0.9 km) of LTS 3 road in stretches of a half mile or more.",
        "No trail was found on this route; it keeps to calm roads and paths.",
    ]
    out = mcp.summary({"distance_m": 4.0 * MI, "mtb": reading(max_level=4)})
    assert out["mtb"] == ["No trail was found on this route; it keeps to calm roads and paths."]


def test_trail_over_the_hardest_level_is_warned_first() -> None:
    said = mcp.mtb_said(
        reading(max_level=1, trail_m=1.9 * MI, singletrack_m=1.5 * MI, over_level_m=0.4 * MI)
    )
    assert said[0].startswith("This route uses 0.4 mi (0.6 km) of trail harder than level 1")
    assert "no way round it was found" in said[0]
    assert said[1] == (
        "1.9 mi (3.1 km) on trail, 1.5 mi (2.4 km) of it mountain-bike singletrack,"
        " up to level 1 (green)."
    )


def test_no_mountain_bike_map_is_said_alone() -> None:
    said = mcp.mtb_said(reading(limited="no_mtb_graph", trail_m=500.0))
    assert len(said) == 1 and "keeps to roads and ordinary paths" in said[0]


def test_a_short_search_and_the_preferred_level_are_said() -> None:
    said = mcp.mtb_said(
        reading(
            max_level=4,
            preferred_level=3,
            limited="time",
            trail_m=3.9 * MI,
            singletrack_m=3.0 * MI,
            easier_m=1.0 * MI,
            harder_m=0.5 * MI,
        )
    )
    assert "ran short of time" in said[0]
    assert said[2] == "1.0 mi (1.6 km) of trail is easier than the preferred level 3 (black)."
    assert said[3] == (
        "0.5 mi (0.8 km) of trail is harder than the preferred level 3 (black),"
        " up to level 4 (red)."
    )
    at = mcp.mtb_said(reading(preferred_level=2, trail_m=MI, singletrack_m=MI))
    assert at[-1] == "Its mountain-bike trails are at the preferred level 2 (blue)."


def test_no_reading_says_nothing() -> None:
    assert mcp.mtb_said(None) is None
    assert "mtb" not in mcp.summary({"distance_m": 1000.0})


# --- M4-3: past the target distance ----------------------------------------------------------


def test_a_route_past_the_target_is_flagged() -> None:
    answer = {
        "distance_m": 5.8 * MI,
        "calm_search": {"over_target_m": 2.8 * MI, "target_distance_m": 4828},
    }
    assert mcp.summary(answer)["over_target"] == (
        "2.8 mi (4.5 km) over the rider's target of 3.0 mi (4.8 km)"
    )
    # A candidate carries its own figure.
    assert mcp.over_target_said({"over_target_m": 1609.344}).startswith("1.0 mi (1.6 km) over")
    within = {"distance_m": 5.9 * MI, "calm_search": {"over_target_m": None}}
    assert "over_target" not in mcp.summary(within)
    assert mcp.over_target_said({"calm_search": {"over_target_m": 0.0}}) is None


def test_the_target_is_described_as_a_limit() -> None:
    text = mcp.RIDE_OPTIONS["target_miles"]["description"]
    assert "longest the ride may be" in text and "soft target distance" not in text


# --- M4-4: mountain-bike trails are trail, not street ----------------------------------------


def stretch(street, a, b, tier, facility=None, surface=None):
    return {
        "kind": "stretch",
        "street": street,
        "from_mi": a,
        "to_mi": b,
        "from_m": round(a * MI),
        "to_m": round(b * MI),
        "tier": tier,
        "facility": facility,
        "surface": surface,
    }


def trail_answer() -> dict:
    """1 mi of road, then 2 mi of White Loop, a mountain-bike trail the map gives no facility."""
    return {
        "distance_m": 3.0 * MI,
        "duration_s": 1800.0,
        "geometry": {
            "type": "LineString",
            "coordinates": [[START[0] + i * 0.1 * LON_MI, START[1]] for i in range(31)],
        },
        "description": [
            stretch("Black Rock Road", 0.0, 1.0, 2, "none"),
            stretch("White Loop", 1.0, 3.0, 1, "none", "unpaved"),
        ],
        "stress_m": {"1": 2.0 * MI, "2": 1.0 * MI},
        "facility_m": {"none": 3.0 * MI},
        "stress_spans": [
            {"from_m": 0, "to_m": round(MI), "tier": 2, "facility": "none"},
            {"from_m": round(MI), "to_m": round(3 * MI), "tier": 1, "facility": "none"},
        ],
        "trail_levels": [{"from_m": round(MI), "to_m": round(3 * MI), "level": 1}],
        "intersections": [],
    }


def test_the_summary_says_mountain_bike_trail_not_ordinary_street() -> None:
    facilities = mcp.summary(trail_answer())["facilities"]
    assert facilities == {
        "mountain-bike trail": "67% (2.0 mi (3.2 km))",
        "ordinary street": "33% (1.0 mi (1.6 km))",
    }


def test_the_roads_and_segments_say_trail() -> None:
    answer = trail_answer()
    roads = mcp.road_list(answer)["roads"]
    assert [(r["road"], r.get("facility")) for r in roads] == [
        ("Black Rock Road", None),
        ("White Loop", "trail"),
    ]
    plan = mcp.Plan([(START[0], START[1]), (START[0] + 3 * LON_MI, START[1])], [], "gravel",
                    answer, None, {})  # fmt: skip
    segments = mcp.route_segments(plan)["segments"]
    assert [(s["road"], s["facility"]) for s in segments] == [
        ("Black Rock Road", "street"),
        ("White Loop", "trail"),
    ]


def test_without_trail_levels_nothing_changes() -> None:
    answer = trail_answer()
    answer["trail_levels"] = None
    assert mcp.summary(answer)["facilities"] == {"ordinary street": "100% (3.0 mi (4.8 km))"}
    assert all("facility" not in r for r in mcp.road_list(answer)["roads"])
