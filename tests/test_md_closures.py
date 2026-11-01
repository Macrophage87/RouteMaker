"""Maryland's Road Closure Reporter (v0.17.0, `routemaker.md_closures`): its counties' and
towns' closures, routed round while in force (Stephen, 2026-11-01: "Real closures, routed
round"). Made-up records in the layer's shape (checked live 2026-11-01)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from routemaker import md_closures as md
from routemaker import workzones as wz

DATA = Path(__file__).resolve().parent / "data" / "closures"
NOW = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
LINE = [[-77.0, 39.0], [-77.0, 39.002]]


def ms(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)


def record(objectid: int = 1, **props) -> dict:
    base = {
        "OBJECTID": objectid,
        "RC_GUID": "{AC2AE548-97A8-46E2-8516-B600C42B8B12}",
        "ClosureStart": ms(2026, 11, 2, 12),
        "ClosureEnd": ms(2026, 11, 4, 21),
        "ClosureType": "Closed",
        "Comments": "Electrical upgrades, entrance to deck closed - follow detour",
        "RoadName": "DRIVE RD",
        "CrossStreet1": "West Patrick Street",
        "CrossStreet2": "Carroll Creek Deck",
        "Jurisdiction": "FREDERICK CITY",
        "closureSummary": "DRIVE RD: Closed, all directions.  All lanes closed.",
    }
    geometry = {"type": "LineString", "coordinates": LINE}
    return {"type": "Feature", "properties": {**base, **props}, "geometry": geometry}


def layer(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


class TestClassify:
    def test_a_closed_road_is_closed(self) -> None:
        assert (
            md.classify("Closed", "X: Closed, all directions.  All lanes closed.")[0] == wz.CLOSED
        )

    def test_emergency_vehicles_only_with_every_lane_closed_is_closed(self) -> None:
        """The Key Bridge, and a crash: no bicycle gets through."""
        summary = "695: Emergency Vehicle Only Access, all directions.  All lanes closed."
        assert md.classify("Emergency Vehicle Only Access", summary)[0] == wz.CLOSED

    def test_local_access_only_is_every_lane_closed_bicycles_not_mentioned(self) -> None:
        summary = "BEL AIR RD: Limited Public Access, all directions.  All lanes closed."
        kind, penalty, _why = md.classify("Limited Public Access", summary)
        assert kind == wz.UNKNOWN and penalty == wz.UNKNOWN_PENALTY_S

    def test_a_lane_closed_with_the_road_open_is_a_lane_penalty(self) -> None:
        for kind, summary in (
            (
                "Limited Public Access",
                "E PATRICK ST: Limited Public Access, all directions. 1 lane(s) open.",
            ),
            ("Curb Lane Closure", "RIVA RD: Curb Lane Closure, Northbound. 1 lane(s) open."),
        ):
            assert md.classify(kind, summary)[:2] == (wz.PENALTY, wz.LANE_PENALTY_S)


class TestParse:
    def test_a_closure_is_routed_round_in_its_hours_only(self) -> None:
        (zone,) = md.parse_sha([layer(record())], NOW)
        assert zone.source == "sha" and zone.kind == wz.CLOSED and not wz.possible(zone)
        assert zone.start == datetime(2026, 11, 2, 12, tzinfo=UTC)
        assert zone.end == datetime(2026, 11, 4, 21, tzinfo=UTC)
        assert not wz.active(zone, NOW)
        assert wz.active(zone, datetime(2026, 11, 3, 12, tzinfo=UTC))
        assert not wz.active(zone, datetime(2026, 11, 4, 21, tzinfo=UTC))

    def test_the_card_says_what_and_where(self) -> None:
        (zone,) = md.parse_sha([layer(record())], NOW)
        assert zone.title == (
            "Drive Rd, West Patrick Street to Carroll Creek Deck: closed (Frederick City)"
        )
        assert zone.road == "Drive Rd"
        assert zone.description.startswith("Electrical upgrades")
        assert zone.url == wz.SOURCE_LINKS["sha"]

    def test_a_direction_is_kept_with_the_road(self) -> None:
        summary = "RIVA RD: Curb Lane Closure, Northbound. 1 lane(s) open."
        (zone,) = md.parse_sha(
            [
                layer(
                    record(
                        RoadName="RIVA RD", ClosureType="Curb Lane Closure", closureSummary=summary
                    )
                )
            ],
            NOW,
        )
        assert zone.road == "Riva Rd northbound" and zone.kind == wz.PENALTY

    def test_a_closure_already_over_is_left_out(self) -> None:
        over = record(ClosureEnd=ms(2026, 10, 30))
        assert md.parse_sha([layer(over)], NOW) == []

    def test_a_record_with_no_end_or_no_line_is_left_out(self) -> None:
        no_end = record(ClosureEnd=None)
        no_line = {**record(2), "geometry": None}
        assert md.parse_sha([layer(no_end, no_line)], NOW) == []

    def test_a_closures_stretches_are_numbered_as_one_closure(self) -> None:
        """The Key Bridge is 69 records under one closure: one marker on the map, so its
        ids are `sha-<closure>-<n>` (closureMap.ts PIECE, routemaker_mcp._closure_id)."""
        zones = md.parse_sha([layer(record(30), record(10), record(20))], NOW)
        prefix = "sha-ac2ae548-97a8-46e2-8516-b600c42b8b12-"
        assert [z.zone_id for z in zones] == [f"{prefix}0", f"{prefix}1", f"{prefix}2"]
        assert [z.line for z in zones] == [tuple(map(tuple, LINE))] * 3

    def test_a_record_in_both_layers_is_read_once(self) -> None:
        zones = md.parse_sha([layer(record()), layer(record())], NOW)
        assert len(zones) == 1

    def test_the_saved_sample_reads(self) -> None:
        document = json.loads((DATA / "sha-road-closures.geojson").read_text())
        zones = md.parse_sha([document], datetime(2026, 10, 15, 19, tzinfo=UTC))
        assert sorted({z.kind for z in zones}) == [wz.CLOSED, wz.PENALTY]
        assert len(zones) == 3, "the closure over in September is left out"


def test_the_reporting_account_is_never_asked_for() -> None:
    """The layer's `Creator` names the account that posted the closure: never asked for, nor
    when it was made or edited."""
    fields = md.FIELDS.split(",")
    assert "Creator" not in fields and "CreationDate" not in fields and "EditDate" not in fields
    from core import closure_sources as cs

    assert all("mdgeodata.md.gov" in url for url in cs.SHA_URLS)


def test_a_closure_in_force_is_routed_round_and_said_as_closed() -> None:
    (zone,) = md.parse_sha([layer(record())], NOW)
    during = datetime(2026, 11, 3, 12, tzinfo=UTC)
    points = [[-77.0005, 38.9995], [-77.0005, 39.0025]]
    plan = wz.for_plan([zone], during, points, {}, during)
    assert plan.exclude and not plan.possible
    assert "marked closed" in wz.heads_up(zone)
    later = wz.for_plan([zone], during + timedelta(days=2), points, {}, during)
    assert not later.exclude
