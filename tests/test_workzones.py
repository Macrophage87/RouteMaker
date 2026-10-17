"""Work zones from the WZDx feeds, read for the planner (FOLLOWUP-WORKZONES, 341-349).

The fixture is hand-made in the WZDx v4.1 shape (tests/data/workzones): neither feed
could be reached from where this was written, so nothing here is agency data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from routemaker import workzones as wz

SAMPLE = Path(__file__).resolve().parent / "data" / "workzones" / "wzdx-v4-sample.geojson"
AT = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)


def zones() -> dict[str, wz.Zone]:
    return {z.zone_id: z for z in wz.parse_feed(json.loads(SAMPLE.read_text()), "md")}


class TestTheFeed:
    def test_work_zones_with_a_line_are_read_and_nothing_else(self) -> None:
        assert sorted(zones()) == [
            "md-wz-closed-bikes",
            "md-wz-closed-unknown",
            "md-wz-flagger",
            "md-wz-lane",
            "md-wz-shoulder",
        ]

    def test_the_fields_the_planner_uses(self) -> None:
        zone = zones()["md-wz-closed-bikes"]
        assert zone.road == "Example Road northbound"
        assert zone.description.startswith("Bridge deck replacement")
        assert zone.start == datetime(2026, 10, 1, tzinfo=UTC)
        assert zone.end == datetime(2026, 12, 1, tzinfo=UTC)
        assert zone.line == ((-77.03, 38.95), (-77.03, 38.953))

    def test_a_multipoint_is_the_line_between_its_ends(self) -> None:
        assert zones()["md-wz-shoulder"].line == ((-77.05, 38.97), (-77.05, 38.973))

    def test_an_unknown_direction_is_not_said(self) -> None:
        assert zones()["md-wz-lane"].road == "Test Street"

    def test_something_that_is_not_a_feed_is_refused(self) -> None:
        with pytest.raises(ValueError):
            wz.parse_feed({"features": []}, "md")

    def test_a_zone_survives_the_round_trip_through_the_stored_copy(self) -> None:
        for zone in zones().values():
            assert wz.Zone.from_json(json.loads(json.dumps(zone.to_json()))) == zone


class TestTheReading:
    """342(3) and 342(4)."""

    def test_closed_to_bicycles_only_when_the_feed_says_so(self) -> None:
        z = zones()
        assert (z["md-wz-closed-bikes"].kind, z["md-wz-closed-bikes"].penalty_s) == (wz.CLOSED, 0)
        # Every lane closed, bicycles not mentioned: penalised, not excluded.
        assert z["md-wz-closed-unknown"].kind == wz.UNKNOWN
        assert z["md-wz-closed-unknown"].penalty_s == wz.UNKNOWN_PENALTY_S

    @pytest.mark.parametrize(
        ("properties", "penalty"),
        [
            (
                {
                    "vehicle_impact": "all-lanes-open",
                    "lanes": [{"type": "shoulder", "status": "closed"}],
                },
                60,
            ),
            ({"vehicle_impact": "all-lanes-open"}, 60),
            ({"vehicle_impact": "some-lanes-closed"}, 120),
            ({"vehicle_impact": "unknown"}, 120),
            ({}, 120),
            ({"vehicle_impact": "alternating-one-way"}, 180),
            ({"vehicle_impact": "flagging"}, 180),
            ({"lanes": [{"type": "general", "status": "alternating-flow"}]}, 180),
            ({"vehicle_impact": "some-lanes-closed-merge-left"}, 120),
        ],
    )
    def test_the_owners_penalties(self, properties, penalty) -> None:
        kind, seconds, why = wz.classify(properties)
        assert (kind, seconds) == (wz.PENALTY, penalty) and why

    def test_all_lanes_closed_with_a_bike_lane_still_open_is_not_closed_to_bicycles(self) -> None:
        kind, _, _ = wz.classify(
            {
                "vehicle_impact": "all-lanes-closed",
                "lanes": [
                    {"type": "general", "status": "closed"},
                    {"type": "bike-lane", "status": "open"},
                ],
            }
        )
        assert kind == wz.UNKNOWN

    def test_the_window(self) -> None:
        lane = zones()["md-wz-lane"]  # 2026-10-10 13:00 to 21:00 UTC
        assert wz.active(lane, datetime(2026, 10, 10, 15, tzinfo=UTC))
        assert not wz.active(lane, datetime(2026, 10, 10, 12, tzinfo=UTC))
        assert not wz.active(lane, datetime(2026, 10, 10, 21, tzinfo=UTC))
        # No end: in force until the feed says otherwise.
        assert wz.active(zones()["md-wz-shoulder"], datetime(2030, 1, 1, tzinfo=UTC))


# A route north along x = -77.0300 through the closed zone, and one along y = 38.9600
# through the unknown-access closure.
NORTH = [(-77.0300, 38.9450), (-77.0300, 38.9580)]
EAST = [(-77.0450, 38.9600), (-77.0300, 38.9600)]


class TestThePlan:
    def test_a_closure_is_excluded_as_a_strip_trimmed_at_both_ends(self) -> None:
        plan = wz.for_plan(zones().values(), AT, NORTH, {"md": "current"})
        assert [z.zone_id for z in plan.excluded] == ["md-wz-closed-bikes"]
        (ring,) = plan.exclude
        assert ring[0] == ring[-1]
        lats = [lat for _, lat in ring]
        # Trimmed 20 m (about 0.00018 degrees) from each end of 38.9500-38.9530.
        assert 38.9501 < min(lats) and max(lats) < 38.9529
        lons = [lon for lon, _ in ring]
        # About 6 m either side.
        assert max(lons) - min(lons) == pytest.approx(12 / 86_700, rel=0.1)

    def test_the_other_zones_are_passable(self) -> None:
        plan = wz.for_plan(zones().values(), AT, NORTH + EAST, {"md": "current"})
        assert {z.zone_id for z in plan.passable} == {
            "md-wz-closed-unknown",
            "md-wz-shoulder",
            "md-wz-flagger",
        }  # the lane closure's window is over at AT

    def test_a_closure_by_a_placed_point_is_warned_of_not_excluded(self) -> None:
        start_inside = [(-77.0300, 38.9515), (-77.0300, 38.9700)]
        plan = wz.for_plan(zones().values(), AT, start_inside, {"md": "current"})
        assert plan.exclude == []
        assert [z.zone_id for z in plan.unexcluded] == ["md-wz-closed-bikes"]

    def test_a_closure_far_from_the_ride_is_not_sent(self) -> None:
        plan = wz.for_plan(
            zones().values(), AT, [(-76.5, 39.3), (-76.49, 39.31)], {"md": "current"}
        )
        assert not plan.any

    def test_the_routers_limits_are_kept(self) -> None:
        many = [
            wz.Zone(f"md-{n}", "md", wz.CLOSED, 0, line, None, None, None, None)
            for n in range(40)
            for line in [((-77.0 + n * 0.001, 38.9), (-77.0 + n * 0.001, 38.903))]
        ]
        plan = wz.for_plan(many, AT, [(-77.0, 38.9), (-76.96, 38.903)], {"md": "current"})
        perimeter, vertices = wz.budget_used(plan.exclude)
        assert vertices <= wz.MAX_VERTICES and perimeter <= wz.MAX_PERIMETER_M
        assert plan.excluded and plan.unexcluded
        assert len(plan.excluded) + len(plan.unexcluded) == 40


class TestAlong:
    def test_a_zone_the_route_runs_along_is_found_with_its_metres(self) -> None:
        (passage,) = wz.along(NORTH, [zones()["md-wz-closed-bikes"]])
        # The zone starts about 556 m up the route, and is trimmed 20 m at each end.
        assert 560 < passage.from_m < 590 and 860 < passage.to_m < 890

    def test_a_street_the_route_only_crosses_is_not_along_it(self) -> None:
        assert wz.along(EAST, [zones()["md-wz-closed-bikes"]]) == []
        crossing = [(-77.0320, 38.9515), (-77.0280, 38.9515)]
        assert wz.along(crossing, [zones()["md-wz-closed-bikes"]]) == []


class TestTheWords:
    def test_one_short_line_said_and_the_source_in_small_print(self) -> None:
        # The owner, 2026-10-17: "the statement is way too verbose. We can cite our sources
        # without all that extra noise." No ": " either, which Ride would cut at.
        zone = zones()["md-wz-closed-unknown"]
        text = wz.heads_up(zone)
        assert text == "Sample Avenue eastbound has every lane closed ahead; bike access unclear."
        assert wz.heads_up(zones()["md-wz-closed-bikes"]).endswith(" marked closed ahead.")
        assert (
            wz.citation(zone) == "Source: Maryland DOT SHA work zones (WZDx, CC0), until Nov 30."
        )  # 00:00 UTC, in Eastern time

    def test_where_the_detour_leaves_the_standard_way(self) -> None:
        assert wz.split_words(zones()["md-wz-closed-bikes"]).endswith(
            " marked closed. Detour posted."
        )
        assert wz.split_words(None) == "The road ahead marked closed. Detour posted."

    def test_a_closure_is_red_and_a_penalty_orange(self) -> None:
        z = zones()
        assert wz.severity(z["md-wz-closed-bikes"]) == "red"
        assert wz.severity(z["md-wz-closed-unknown"]) == "red"
        assert wz.severity(z["md-wz-shoulder"]) == "orange"
