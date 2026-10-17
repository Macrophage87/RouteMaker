"""DC's closures read for the planner (v0.7.0 plan, "DC closures source"): DDOT's TOPS
permits, MPD traffic advisories, AlertDC's traffic items and NPS alerts. Pure parsing,
on saved sample pages (tests/data/closures): none of the four hosts answers through the
proxy this was built behind."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from routemaker import dc_closures as dc
from routemaker import workzones as wz

DATA = Path(__file__).resolve().parent / "data" / "closures"
NOW = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)


def text(name: str) -> str:
    return (DATA / name).read_text()


class TestPermits:
    def permits(self):
        return {
            p.permit_id: p for p in dc.parse_permits(json.loads(text("tops-permits.geojson")), NOW)
        }

    def test_only_active_permits_that_close_a_road_or_block_a_bike_lane(self) -> None:
        # 103 closes a travel lane only; 104 has expired; 105 is cancelled; 106 has no point.
        assert sorted(self.permits()) == ["PA261001", "PA261002"]

    def test_a_road_closure_and_a_blocked_bike_lane(self) -> None:
        found = self.permits()
        closed, lane = found["PA261001"], found["PA261002"]
        assert closed.road_closed and closed.point == (-77.0305, 38.8982)
        assert closed.end == datetime(2026, 10, 26, 2, tzinfo=UTC)
        assert not lane.road_closed and lane.bike_lane_ft == 80
        line = ((-77.031, 38.8982), (-77.030, 38.8982))
        assert dc.permit_zone(closed, line).kind == wz.CLOSED
        zone = dc.permit_zone(lane, line)
        assert zone.kind == wz.LANE and zone.zone_id == "dc-PA261002"
        assert zone.title == "15TH ST NW: bike lane blocked (permit PA261002)"

    def test_arcgis_json_and_dates_as_text(self) -> None:
        document = {
            "features": [
                {
                    "attributes": {
                        "PermitNumber": "X1",
                        "Status": "ACTIVE",
                        "IsRoadClosed": 1,
                        "ExpirationDate": "10/20/2026",
                    },
                    "geometry": {"x": -77.02, "y": 38.9},
                }
            ]
        }
        (permit,) = dc.parse_permits(document, NOW)
        assert permit.end == datetime(2026, 10, 20, 4, tzinfo=UTC)  # midnight in DC
        # The link opens this permit's own record, by the answer's own spelling of the field.
        assert permit.url == (
            f"{dc.TOPS_LAYER}/query?where=PermitNumber%3D%27X1%27&outFields=%2A&f=html"
        )
        assert dc.permit_zone(permit, ((-77.02, 38.9), (-77.01, 38.9))).url == permit.url

    def test_a_permit_known_only_by_its_object_id_links_by_it(self) -> None:
        assert dc.permit_url(None, 42) == f"{dc.TOPS_LAYER}/query?objectIds=42&outFields=%2A&f=html"
        assert "O%27%27BRIEN" in dc.permit_url("PERMITNUMBER", "O'BRIEN")
        with pytest.raises(ValueError):
            dc.parse_permits({"error": {"code": 400}}, NOW)


class TestBlock:
    # A street running east, crossed by two others 100 m apart, with the permit between them.
    WAY = [(-77.0320, 38.9000), (-77.0300, 38.9000), (-77.0280, 38.9000)]
    A = [(-77.0310, 38.8990), (-77.0310, 38.9010)]
    B = [(-77.0298, 38.8990), (-77.0298, 38.9010)]

    def test_the_block_runs_from_the_junction_before_to_the_one_after(self) -> None:
        block = dc.block_of((-77.0305, 38.9001), self.WAY, [self.A, self.B])
        assert block is not None
        assert block[0][0] == pytest.approx(-77.0310, abs=1e-6)
        assert block[-1][0] == pytest.approx(-77.0298, abs=1e-6)

    def test_with_no_cross_street_it_is_the_whole_way(self) -> None:
        block = dc.block_of((-77.0305, 38.9001), self.WAY, [])
        assert block[0][0] == pytest.approx(-77.0320) and block[-1][0] == pytest.approx(-77.0280)

    def test_a_permit_at_a_junction_still_marks_a_stretch(self) -> None:
        block = dc.block_of((-77.0310, 38.9000), self.WAY, [self.A, self.A])
        lat0 = 38.9
        length = wz._length([wz._xy(p[0], p[1], lat0) for p in block])
        assert length >= dc.MIN_BLOCK_M - 1


class TestSegments:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            (
                "Constitution Avenue from 14th Street to 18th Street, NW",
                ("Constitution Avenue NW", "14th Street NW", "18th Street NW"),
            ),
            (
                "17th Street, NW between Constitution Avenue and E Street, NW",
                ("17th Street NW", "Constitution Avenue NW", "E Street NW"),
            ),
            (
                "Due to fire department activity, Pennsylvania Avenue, SE is closed from 2nd Street"
                " to 4th Street, SE until 6:00 PM.",
                ("Pennsylvania Avenue SE", "2nd Street SE", "4th Street SE"),
            ),
            (
                "• Southbound Rock Creek Parkway from Virginia Avenue to Ohio Drive (both lanes)",
                ("Rock Creek Parkway", "Virginia Avenue", "Ohio Drive"),
            ),
        ],
    )
    def test_x_from_a_to_b(self, line, expected) -> None:
        assert dc.parse_segment(line) == expected

    @pytest.mark.parametrize(
        "line",
        [
            "The following streets will be closed from 4:30 am to 1:30 pm:",
            "Emergency No Parking will be in effect from 12:01 am to 3:00 pm",
            "Motorists should expect delays in the area.",
            "",
        ],
    )
    def test_anything_else_is_not_a_segment(self, line) -> None:
        assert dc.parse_segment(line) is None

    def test_street_names_meet_across_abbreviations_and_quadrants(self) -> None:
        assert dc.street_key("Constitution Ave., NW") == "constitution avenue northwest"
        assert dc.names_match("Constitution Avenue Northwest", "Constitution Ave NW")
        assert dc.names_match("E Street Northwest", "E St NW")
        assert dc.street_key("St Elmo Ave") == "saint elmo avenue"
        assert dc.names_match("Constitution Avenue", "Constitution Avenue NW")
        assert not dc.names_match("Constitution Avenue Northeast", "Constitution Avenue NW")


class TestMpd:
    def test_only_traffic_advisories_on_mpd_are_listed(self) -> None:
        links = dc.traffic_advisory_links(text("mpd-newsroom.html"))
        assert [url.rsplit("/", 1)[-1] for _t, url in links] == [
            "traffic-advisory-street-closures-labor-day-concert-national-mall",
            "traffic-advisory-motorcade-route-state-visit",
        ]
        # The other releases, and a link off MPD's site, are passed over on their titles.
        assert not any("arrest" in u or "suspect" in u or "example" in u for _t, u in links)

    def test_a_release_is_read_into_segments_with_their_windows(self) -> None:
        advisory = dc.parse_mpd_release(
            text("mpd-traffic-advisory.html"), "https://mpdc.dc.gov/node/1845231"
        )
        assert advisory is not None and advisory.source == "mpd"
        assert advisory.published == datetime(2026, 9, 4, 19, 12, tzinfo=UTC)
        got = [(s.street, s.from_street, s.to_street, s.start, s.end) for s in advisory.segments]
        morning = (
            datetime(2026, 9, 7, 8, 30, tzinfo=UTC),
            datetime(2026, 9, 7, 17, 30, tzinfo=UTC),
        )
        overnight = (datetime(2026, 9, 7, 18, tzinfo=UTC), datetime(2026, 9, 8, 6, tzinfo=UTC))
        assert got == [
            ("Constitution Avenue NW", "14th Street NW", "18th Street NW", *morning),
            ("15th Street NW", "Constitution Avenue SW", "Independence Avenue SW", *morning),
            ("17th Street NW", "Constitution Avenue NW", "E Street NW", *morning),
            ("Madison Drive NW", "3rd Street NW", "14th Street NW", *overnight),
            ("Jefferson Drive SW", "3rd Street SW", "14th Street SW", *overnight),
        ]
        # Emergency No Parking is not a closure; a segment under a date with no times is
        # text to check, never guessed.
        assert advisory.unparsed == ["Independence Avenue, SW from 3rd Street to 7th Street, SW"]
        notice = advisory.notice()
        assert notice.area == dc.DC_AREA and notice.url == "https://mpdc.dc.gov/node/1845231"
        assert "Independence Avenue" in notice.text

    def test_a_release_that_is_not_a_traffic_advisory_is_not_read(self) -> None:
        page = "<html><body><h1>Arrest Made in an Incident</h1><p>Text.</p></body></html>"
        assert dc.parse_mpd_release(page, "https://mpdc.dc.gov/release/x") is None

    def test_a_placed_segment_is_a_closure_with_its_source(self) -> None:
        advisory = dc.parse_mpd_release(
            text("mpd-traffic-advisory.html"), "https://mpdc.dc.gov/node/1845231"
        )
        zone = dc.segment_zone(
            advisory, 0, advisory.segments[0], [(-77.03, 38.89), (-77.04, 38.89)]
        )
        assert zone.kind == wz.CLOSED and zone.source == "mpd"
        assert zone.title == "Constitution Avenue NW closed, 14th Street NW to 18th Street NW"
        assert wz.source_text(zone) == "MPD traffic advisory, Sep 4"
        assert wz.when_text(zone, NOW, True) == "Closed Mon, Sep 7 4:30 am to 1:30 pm"


class TestAlertDc:
    def test_only_traffic_items_and_never_crime_or_weather(self) -> None:
        advisories = dc.parse_alertdc(text("alertdc-nrss.xml"), NOW)
        assert [a.advisory_id for a in advisories] == ["alertdc-90211", "alertdc-90208"]
        stored = json.dumps([a.notice().to_json() for a in advisories])
        for word in ("shooting", "Police", "police", "Wind", "1500 block"):
            assert word not in stored

    def test_a_road_closure_until_a_time_and_a_bridge_opening_as_text(self) -> None:
        closure, bridge = dc.parse_alertdc(text("alertdc-nrss.xml"), NOW)
        (segment,) = closure.segments
        assert (segment.street, segment.from_street, segment.to_street) == (
            "Pennsylvania Avenue SE",
            "2nd Street SE",
            "4th Street SE",
        )
        assert segment.end == datetime(2026, 10, 15, 22, tzinfo=UTC)  # 6 pm in DC
        assert bridge.segments == [] and "marine traffic" in bridge.notice().text

    def test_an_old_item_with_no_end_has_passed(self) -> None:
        later = NOW + timedelta(days=1)
        assert dc.parse_alertdc(text("alertdc-nrss.xml"), later) == []

    @pytest.mark.parametrize(
        ("title", "categories", "traffic"),
        [
            ("DDOT Traffic Alert: Road Closure", [], True),
            ("Road closed for police activity", [], False),
            ("Shooting investigation", ["Traffic"], False),
            ("Wind Advisory", ["Weather"], False),
            ("Anything", ["Transportation"], True),
            ("Missing person", [], False),
        ],
    )
    def test_is_traffic(self, title, categories, traffic) -> None:
        assert dc.is_traffic(title, categories) is traffic


class TestNps:
    def test_park_closures_and_cautions_for_our_parks_only(self) -> None:
        notices = dc.parse_nps(json.loads(text("nps-alerts.json")))
        assert [(n.area, n.category) for n in notices] == [
            ("rocr", "Park Closure"),
            ("gwmp", "Caution"),
        ]
        # An alert with no link of its own links to its park's conditions page.
        assert notices[1].url == "https://www.nps.gov/gwmp/planyourvisit/conditions.htm"

    def test_a_park_notice_is_on_a_route_through_the_park_and_never_a_closure(self) -> None:
        notices = dc.parse_nps(json.loads(text("nps-alerts.json")))
        through_rock_creek = [(-77.05, 38.93), (-77.05, 38.95)]
        downtown_east = [(-76.99, 38.90), (-76.98, 38.90)]
        assert [n.area for n in dc.notices_along(notices, through_rock_creek, NOW)] == ["rocr"]
        assert dc.notices_along(notices, downtown_east, NOW) == []
        assert all(isinstance(n, dc.Notice) for n in notices)


def test_notices_and_zones_survive_the_stored_copy() -> None:
    advisory = dc.parse_mpd_release(text("mpd-traffic-advisory.html"), "https://mpdc.dc.gov/node/1")
    notice = advisory.notice()
    assert dc.Notice.from_json(json.loads(json.dumps(notice.to_json()))) == notice
    zone = dc.segment_zone(advisory, 1, advisory.segments[1], [(-77.03, 38.89), (-77.03, 38.88)])
    assert wz.Zone.from_json(json.loads(json.dumps(zone.to_json()))) == zone


class TestRideTime:
    """Closures follow the ride, not today; one with no end "may still apply" later."""

    LINE = ((-77.040, 38.900), (-77.030, 38.900))
    POINTS = [(-77.05, 38.90), (-77.02, 38.90)]

    def zone(self, end=None, start=None, kind=wz.CLOSED):
        return wz.Zone("mpd-1", "mpd", kind, 0, self.LINE, "K St NW", None, start, end)

    def test_a_saturday_ride_sees_saturday_closures_only(self) -> None:
        saturday = NOW + timedelta(days=2)
        today_only = self.zone(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=5))
        plan = wz.for_plan([today_only], saturday, self.POINTS, {}, now=NOW)
        assert not plan.any
        plan = wz.for_plan([today_only], NOW, self.POINTS, {}, now=NOW)
        assert [z.zone_id for z in plan.excluded] == ["mpd-1"]

    def test_no_end_on_a_later_ride_may_still_apply_and_is_not_routed_round(self) -> None:
        plan = wz.for_plan([self.zone()], NOW + timedelta(days=2), self.POINTS, {}, now=NOW)
        assert plan.uncertain and not plan.excluded and not plan.exclude
        plan = wz.for_plan([self.zone()], NOW, self.POINTS, {}, now=NOW)
        assert plan.excluded and not plan.uncertain

    def test_route_through_anyway_and_a_blocked_lane(self) -> None:
        lane = wz.Zone("dc-2", "dc", wz.LANE, 0, self.LINE, "K St NW", None, None, None)
        plan = wz.for_plan(
            [self.zone(end=NOW + timedelta(days=1)), lane],
            NOW,
            self.POINTS,
            {},
            now=NOW,
            bypass=["mpd-1"],
        )
        assert [z.zone_id for z in plan.bypassed] == ["mpd-1"] and not plan.exclude
        assert [z.zone_id for z in plan.lanes] == ["dc-2"] and not plan.passable

    def test_the_card_words(self) -> None:
        zone = self.zone(start=NOW + timedelta(hours=2), end=NOW + timedelta(days=5))
        assert wz.when_text(zone, NOW, False) == "Closed from Oct 15 until Oct 20"
        permit = wz.Zone(
            "dc-1", "dc", wz.CLOSED, 0, self.LINE, None, None, None, NOW + timedelta(days=5)
        )
        assert wz.when_text(permit, NOW, False) == "Permit: road closed until Oct 20"
        assert wz.when_text(self.zone(), NOW, True).endswith("may still apply on your ride day")
        assert wz.effect_text(zone, wz.ROUTED_ROUND, 240) == "Detour adds about 4 min"
        assert wz.effect_text(zone, wz.NO_EFFECT, None) == "No effect on your route"
        assert wz.effect_text(zone, wz.ROUTED_ROUND, 10) == "Detour adds under a minute"
