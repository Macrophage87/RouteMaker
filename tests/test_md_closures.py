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

    def test_emergency_vehicles_only_is_closed_even_with_a_lane_open(self) -> None:
        summary = "X: Emergency Vehicle Only Access, all directions. 1 lane(s) open."
        assert md.classify("Emergency Vehicle Only Access", summary)[0] == wz.CLOSED

    def test_one_direction_closed_is_a_step_lighter(self) -> None:
        """Review: the line carries no direction, and the other way is open."""
        closed = "RIVA RD: Closed, Northbound.  All lanes closed."
        assert md.classify("Closed", closed)[0] == wz.UNKNOWN
        local = "JFK SB HWY: Limited Public Access, Southbound.  All lanes closed."
        assert md.classify("Limited Public Access", local)[0] == wz.PENALTY


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

    def test_a_closures_stretches_are_numbered_as_one_closure_along_the_ground(self) -> None:
        """The Key Bridge is 69 records under one closure: one marker on the map, so its
        ids are `sha-<closure>-<n>` (closureMap.ts PIECE, routemaker_mcp._closure_id),
        numbered by where each stretch lies, not by record, so posting it again keeps them."""

        def at(objectid: int, west: float) -> dict:
            feature = record(objectid)
            feature["geometry"] = {
                "type": "LineString",
                "coordinates": [[west, 39.0], [west + 0.001, 39.0]],
            }
            return feature

        zones = md.parse_sha([layer(at(30, -77.0), at(10, -77.002), at(20, -77.001))], NOW)
        prefix = "sha-ac2ae548-97a8-46e2-8516-b600c42b8b12-"
        assert [z.zone_id for z in zones] == [f"{prefix}0", f"{prefix}1", f"{prefix}2"]
        assert [z.line[0][0] for z in zones] == [-77.002, -77.001, -77.0]
        again = md.parse_sha([layer(at(99, -77.001), at(98, -77.0), at(97, -77.002))], NOW)
        assert [(z.zone_id, z.line) for z in again] == [(z.zone_id, z.line) for z in zones]

    def test_a_stretch_in_both_layers_is_read_once(self) -> None:
        zones = md.parse_sha([layer(record(1)), layer(record(2))], NOW)
        assert len(zones) == 1

    def test_two_records_sharing_an_objectid_across_layers_are_both_kept(self) -> None:
        """The layers are separate tables: an id is not a stretch."""
        other = record(1, RC_GUID="{00000000-0000-4000-8000-000000000009}")
        assert len(md.parse_sha([layer(record(1)), layer(other)], NOW)) == 2

    def test_a_contact_in_the_comments_is_not_kept(self) -> None:
        text = "Detour posted. Questions: J. Doe, 410-555-0123 or jdoe@example.md.gov"
        (zone,) = md.parse_sha([layer(record(Comments=text))], NOW)
        assert "555" not in zone.description and "@" not in zone.description

    def test_route_numbers_keep_their_capitals(self) -> None:
        (zone,) = md.parse_sha([layer(record(RoadName="MD 7", CrossStreet1="US 40"))], NOW)
        assert zone.road == "MD 7" and zone.title.startswith("MD 7, US 40 to")

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


class Fetch:
    def __init__(self, answers: dict[str, bytes]) -> None:
        self.answers, self.asked = answers, []

    def __call__(self, url: str, timeout: float, headers: dict) -> bytes:
        self.asked.append(url)
        return next(body for key, body in self.answers.items() if key in url)


class TestReader:
    def test_both_layers_are_asked_for_the_closures_fields_only(self) -> None:
        from core import closure_sources as cs

        empty = json.dumps(layer()).encode()
        fetch = Fetch(
            {"RoadClosureActive": json.dumps(layer(record())).encode(), "RoadClosurePlanned": empty}
        )
        zones, notices = cs.read_sha(fetch, None, None, NOW, lambda s: None)
        assert len(zones) == 1 and notices == []
        assert len(fetch.asked) == 2
        for url in fetch.asked:
            assert "outFields=" + md.FIELDS.replace(",", "%2C") in url and "Creator" not in url

    def test_a_refused_or_cut_short_layer_fails_the_read(self) -> None:
        import pytest

        from core import closure_sources as cs
        from core.workzones import FeedError

        good = json.dumps(layer()).encode()
        for bad in (
            b'{"error": {"code": 400}}',
            json.dumps({**layer(), "exceededTransferLimit": True}).encode(),
        ):
            fetch = Fetch({"RoadClosureActive": good, "RoadClosurePlanned": bad})
            with pytest.raises(FeedError):
                cs.read_sha(fetch, None, None, NOW, lambda s: None)
