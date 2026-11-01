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


class TestTheNewYear:
    """Audit 2026-10-29: a date without a year took the year it was posted in, so a late
    December notice of an early January closure read as last January's, already over."""

    DEC_29 = datetime(2026, 12, 29, 15, 0, tzinfo=UTC)

    def test_an_mpd_window_in_january_posted_in_december_is_next_year(self) -> None:
        segments, _unparsed, start, end = dc.read_lines(
            [
                "Friday, January 1 from 7 am to 5 pm",
                "Constitution Avenue NW from 14th Street NW to 18th Street NW",
            ],
            self.DEC_29,
        )
        (segment,) = segments
        assert segment.start == datetime(2027, 1, 1, 12, tzinfo=UTC)
        assert segment.end == datetime(2027, 1, 1, 22, tzinfo=UTC)

    def test_a_recent_date_keeps_its_year(self) -> None:
        segments, *_ = dc.read_lines(
            [
                "Monday, December 28 from 7 am to 5 pm",
                "Constitution Avenue NW from 14th Street NW to 18th Street NW",
            ],
            self.DEC_29,
        )
        assert segments[0].start == datetime(2026, 12, 28, 12, tzinfo=UTC)
        # A year written out is kept as it is.
        assert dc._dates("January 1, 2026", 2026, self.DEC_29.date()) == [
            datetime(2026, 1, 1).date()
        ]

    def test_an_alertdc_end_in_january_posted_in_december_is_next_year(self) -> None:
        end = dc._alert_end(
            "M Street SE is closed from 1st Street SE to 4th Street SE until 6 pm January 2.",
            self.DEC_29,
        )
        assert end == datetime(2027, 1, 2, 23, tzinfo=UTC)


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


class TestAlertDcList:
    """AlertDC's public list is an HTML table, not RSS (checked live 2026-11-01): before,
    the reader raised "not an RSS feed" on every run and no AlertDC closure was used."""

    def test_the_html_list_is_read_not_refused(self) -> None:
        advisories = dc.parse_alertdc(text("alertdc-list.html"), NOW)
        assert [a.advisory_id for a in advisories] == [
            "alertdc-90211",
            "alertdc-90207",
            "alertdc-90205",
        ]
        assert advisories[0].url == (
            "https://trainingtrack.hsema.dc.gov/NRss/RssFeed/AlertDetails/90211"
        )
        # 2:05 PM in DC on Oct 15 is 18:05 UTC.
        assert advisories[0].published == datetime(2026, 10, 15, 18, 5, tzinfo=UTC)

    def test_crime_and_weather_items_are_dropped_unread(self) -> None:
        stored = json.dumps(
            [a.notice().to_json() for a in dc.parse_alertdc(text("alertdc-list.html"), NOW)]
        )
        for word in ("shooting", "1500 block", "911", "Wind", "District"):
            assert word not in stored

    def test_a_closure_until_a_time_and_a_bridge_opening_as_text(self) -> None:
        closure, _fire, bridge = dc.parse_alertdc(text("alertdc-list.html"), NOW)
        assert bridge.segments == [] and "marine traffic" in bridge.notice().text
        (segment,) = closure.segments
        assert (segment.street, segment.from_street, segment.to_street) == (
            "Pennsylvania Avenue SE",
            "2nd Street SE",
            "4th Street SE",
        )
        assert segment.end == datetime(2026, 10, 15, 22, tzinfo=UTC)  # 6 pm in DC

    def test_each_bulleted_block_is_its_own_segment(self) -> None:
        fire = dc.parse_alertdc(text("alertdc-list.html"), NOW)[1]
        assert [(s.street, s.from_street, s.to_street) for s in fire.segments] == [
            ("Connecticut Avenue NW", "Ellicott Street NW", "Cumberland Street NW"),
            ("Davenport Street NW", "Connecticut Avenue NW", "32nd Street NW"),
        ]

    def test_a_reopened_road_ends_its_closure_and_is_never_one(self) -> None:
        """Before: the crash closure stood for 12 hours after AlertDC said it reopened."""
        ids = [a.advisory_id for a in dc.parse_alertdc(text("alertdc-list.html"), NOW)]
        assert "alertdc-90208" not in ids and "alertdc-90209" not in ids

    def test_the_closure_stands_until_the_reopening_is_posted(self) -> None:
        page = text("alertdc-list.html")
        rows = page.split("<tr>")
        without_update = "<tr>".join(r for r in rows if "AlertDetails/90209" not in r)
        (crash,) = [
            a for a in dc.parse_alertdc(without_update, NOW) if a.advisory_id == "alertdc-90208"
        ]
        (segment,) = crash.segments
        assert (segment.street, segment.from_street, segment.to_street) == (
            "Naylor Road SE",
            "Alabama Avenue SE",
            "Marion Barry Avenue SE",
        )

    @staticmethod
    def page(*rows: tuple[str, str, str, str]) -> str:
        """A list page of (local time, id, title, text) rows, newest first."""
        cells = "".join(
            f'<tr><td class="head">{when}</td><td class="head"><b>'
            f'<a href="/NRss/RssFeed/AlertDetails/{i}">{title}</a></b><br />{body}</td></tr>'
            for when, i, title, body in rows
        )
        return f"<html><body><table><tbody>{cells}</tbody></table></body></html>"

    CRASH = "[AlertDC] Road Closure / Vehicle Crash (Naylor Road, SE)"
    FINAL = "[AlertDC] Final Update: Road Closure / Vehicle Crash (Naylor Road, SE)"

    def test_a_partial_reopening_keeps_what_is_still_closed(self) -> None:
        page = self.page(
            (
                "10/15/2026 2:40 PM",
                "3",
                "[AlertDC] Update: Road Closures / Vehicle Crash (Naylor Road, SE)",
                "The 2700 block of Naylor Road, SE, between Alabama Avenue and Marion Barry"
                " Avenue has reopened. The 2800 block of Naylor Road, SE, between Marion Barry"
                " Avenue and 30th Street is still closed.",
            ),
            (
                "10/15/2026 2:00 PM",
                "1",
                self.CRASH,
                "MPD reports the 2700 block of Naylor Road, SE, between Alabama Avenue and"
                " Marion Barry Avenue is closed due to a vehicle crash.",
            ),
        )
        (update,) = dc.parse_alertdc(page, NOW)
        assert [(s.from_street, s.to_street) for s in update.segments] == [
            ("Marion Barry Avenue SE", "30th Street SE")
        ]

    def test_cleared_wording_inside_a_closure_keeps_it(self) -> None:
        page = self.page(
            (
                "10/15/2026 2:00 PM",
                "1",
                self.CRASH,
                "MPD reports the crash has cleared but the 2700 block of Naylor Road, SE,"
                " between Alabama Avenue and Marion Barry Avenue is closed for repairs.",
            )
        )
        assert [a.advisory_id for a in dc.parse_alertdc(page, NOW)] == ["alertdc-1"]

    def test_a_reopening_ends_only_its_own_stretch_of_a_shared_title(self) -> None:
        """Two crashes under one generic title: the first one's reopening keeps the second."""
        page = self.page(
            (
                "10/15/2026 2:40 PM",
                "3",
                self.FINAL,
                "MPD reports the 2700 block of Naylor Road, SE, between Alabama Avenue and"
                " Marion Barry Avenue has reopened to traffic.",
            ),
            (
                "10/15/2026 2:30 PM",
                "2",
                self.CRASH,
                "MPD reports the 2800 block of Naylor Road, SE, between Marion Barry Avenue"
                " and 30th Street is closed due to a vehicle crash.",
            ),
            (
                "10/15/2026 2:00 PM",
                "1",
                self.CRASH,
                "MPD reports the 2700 block of Naylor Road, SE, between Alabama Avenue and"
                " Marion Barry Avenue is closed due to a vehicle crash.",
            ),
        )
        assert [a.advisory_id for a in dc.parse_alertdc(page, NOW)] == ["alertdc-2"]

    def test_open_and_lane_sentences_are_never_closures(self) -> None:
        for sentence in (
            "The 2700 block of Naylor Road, SE, between Alabama Avenue and Marion Barry"
            " Avenue remains open to traffic.",
            "MPD reports the left lane of Naylor Road, SE, between Alabama Avenue and"
            " Marion Barry Avenue is closed.",
        ):
            page = self.page(("10/15/2026 2:00 PM", "1", self.CRASH, sentence))
            assert all(a.segments == [] for a in dc.parse_alertdc(page, NOW))

    def test_the_repeated_hour_keeps_the_reopening_after_its_closure(self) -> None:
        """Nov 1, 2026: a closure at 1:50 AM EDT and its reopening at 1:10 AM EST, 20
        minutes later, both read "1:xx AM"; the reopening still ends the closure."""
        page = self.page(
            ("11/1/2026 1:10 AM", "2", self.FINAL, "MPD reports the road has reopened."),
            (
                "11/1/2026 1:50 AM",
                "1",
                self.CRASH,
                "MPD reports the 2700 block of Naylor Road, SE, between Alabama Avenue and"
                " Marion Barry Avenue is closed.",
            ),
        )
        assert dc.parse_alertdc(page, datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == []

    def test_a_list_whose_rows_no_longer_read_fails(self) -> None:
        drifted = (
            "<table><tr><td>11/1/2026 1:10 AM</td>"
            "<td><a href='/NRss/RssFeed/AlertDetails/1'>x</a></td></tr></table>"
        )
        with pytest.raises(ValueError):
            dc.parse_alertdc(drifted, NOW)
        assert dc.parse_alertdc("<html><table><tbody></tbody></table></html>", NOW) == []

    def test_a_page_that_is_neither_rss_nor_the_list_fails_the_read(self) -> None:
        with pytest.raises(ValueError):
            dc.parse_alertdc("<html><body>Service unavailable</body></html>", NOW)

    def test_an_old_item_with_no_end_has_passed(self) -> None:
        assert dc.parse_alertdc(text("alertdc-list.html"), NOW + timedelta(days=1)) == []


class TestNps:
    def test_park_closures_and_cautions_for_our_parks_only(self) -> None:
        notices = dc.parse_nps(json.loads(text("nps-alerts.json")))
        assert [(n.area, n.category) for n in notices] == [
            ("rocr", "Park Closure"),
            ("gwmp", "Caution"),
        ]
        # An alert with no link of its own links to its park's conditions page.
        assert notices[1].url == "https://www.nps.gov/gwmp/planyourvisit/conditions.htm"

    def test_a_link_with_a_second_address_run_into_it_gives_the_parks_page(self) -> None:
        alert = {
            "id": "x1",
            "parkCode": "rocr",
            "category": "Park Closure",
            "title": "Waterside Drive NW Road Closure",
        }
        bad = dc.parse_nps(
            {"data": [{**alert, "url": "https://www.nps.govhttos://www.nps.gov/rocr"}]}
        )
        assert bad[0].url == "https://www.nps.gov/rocr/planyourvisit/conditions.htm"
        good = dc.parse_nps(
            {"data": [{**alert, "url": "https://www.nps.gov/rocr/learn/news/x.htm"}]}
        )
        assert good[0].url == "https://www.nps.gov/rocr/learn/news/x.htm"

    @pytest.mark.parametrize(
        ("url", "ok"),
        [
            ("https://www.nps.gov/rocr/planyourvisit/conditions.htm", True),
            ("https://mpdc.dc.gov/release/%20TRAFFIC-ADVISORY", True),
            ("https://www.nps.govhttos://www.nps.gov/rocr", False),
            ("https://www.nps.gov/https://www.nps.gov/rocr", False),
            ("http://www.nps.gov/rocr", False),
            ("https://", False),
            ("www.nps.gov/rocr", False),
        ],
    )
    def test_web_link(self, url, ok) -> None:
        assert dc.web_link(url) is ok

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
        lane = wz.Zone("mpd-2", "mpd", wz.LANE, 0, self.LINE, "K St NW", None, None, None)
        plan = wz.for_plan(
            [self.zone(end=NOW + timedelta(days=1)), lane],
            NOW,
            self.POINTS,
            {},
            now=NOW,
            bypass=["mpd-1"],
        )
        assert [z.zone_id for z in plan.bypassed] == ["mpd-1"] and not plan.exclude
        assert [z.zone_id for z in plan.lanes] == ["mpd-2"] and not plan.passable

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

    def test_a_date_in_another_year_says_its_year(self) -> None:
        # P11: "Closed through Aug 31" for 2027 read as over, and a 2023 notice as new.
        next_year = self.zone(end=datetime(2027, 8, 31, 16, 0, tzinfo=UTC))
        assert wz.when_text(next_year, NOW, False) == "Closed until Aug 31, 2027"
        assert wz.date_text(datetime(2027, 8, 31, 16, 0, tzinfo=UTC), NOW) == "Aug 31, 2027"
        assert wz.date_text(datetime(2026, 8, 31, 16, 0, tzinfo=UTC), NOW) == "Aug 31"
        # No `now`, no year (as before).
        assert wz.date_text(datetime(2027, 8, 31, 16, 0, tzinfo=UTC)) == "Aug 31"
        # A whole-day source's last day, and a later start, each with its year.
        reviewer = wz.Zone(
            "reviewer-1-0",
            "reviewer",
            wz.CLOSED,
            0,
            self.LINE,
            "Trail",
            None,
            datetime(2027, 1, 4, 5, 0, tzinfo=UTC),
            datetime(2027, 1, 9, 5, 0, tzinfo=UTC),
        )
        assert wz.when_text(reviewer, NOW, False) == "Closed from Jan 4, 2027 through Jan 8, 2027"
        # The region's time decides the year: 2 am UTC on Jan 1 is still Dec 31 here.
        assert wz.date_text(datetime(2026, 1, 1, 2, 0, tzinfo=UTC), NOW) == "Dec 31, 2025"

    def test_a_park_notice_posted_in_another_year_says_its_year(self) -> None:
        old = dc.Notice(
            "nps-1",
            "nps",
            "Trail closed",
            "",
            None,
            "rocr",
            published=datetime(2023, 11, 8, 15, 0, tzinfo=UTC),
        )
        assert dc.notice_when_text(old, NOW, False) == "Posted Nov 8, 2023"
        new = dc.Notice(
            "nps-2",
            "nps",
            "Trail closed",
            "",
            None,
            "rocr",
            published=datetime(2026, 10, 1, 15, 0, tzinfo=UTC),
        )
        assert dc.notice_when_text(new, NOW, False) == "Posted Oct 1"
        long = dc.Notice(
            "nps-3",
            "nps",
            "Bridge work",
            "",
            None,
            "rocr",
            start=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
            end=datetime(2027, 3, 1, 15, 0, tzinfo=UTC),
        )
        assert dc.notice_when_text(long, NOW, False) == "Sep 1 to Mar 1, 2027"
