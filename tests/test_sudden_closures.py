"""Sudden closures from AlertDC (Stephen 2026-11-12, of a shooting's road closures at Logan
Circle): police activity closures read for their closures only and avoided by a wide margin, a
closure at one junction placed as a small area, and AlertDC read every minute, only where its
page changed. The network and the placing are fakes; the database is real."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core import closure_sources as sources
from core import workzones
from core.models import BikeshareFeedCache
from routemaker import dc_closures as dc
from routemaker import workzones as wz

DATA = Path(__file__).resolve().parent / "data" / "closures"
PAGE = (DATA / "alertdc-police.html").read_text()
# 8:30 AM in the District, ten minutes after the police closure was posted.
NOW = datetime(2026, 11, 12, 13, 30, tzinfo=UTC)
# The three junctions, roughly where they are.
P15 = [-77.0353, 38.9097]
P14 = [-77.0320, 38.9097]
Q15 = [-77.0353, 38.9110]
GEORGIA = [-77.0262, 38.9603]
# Words of the incident, which must never be kept or shown.
INCIDENT_WORDS = ("shooting", "Shooting", "Suspect", "suspect", "armed", "Investigation")


def advisories(now=NOW):
    return {a.advisory_id: a for a in dc.parse_alertdc(PAGE, now)}


# --- Reading --------------------------------------------------------------------------


def test_a_police_road_closure_is_read_for_its_closures_alone() -> None:
    police = advisories()["alertdc-91001"]
    assert police.police and police.title == dc.POLICE_TITLE
    assert [(c.a, c.b) for c in police.corners] == [
        ("15th Street NW", "P Street NW"),
        ("14th Street NW", "P Street NW"),
        ("15th Street NW", "Q Street NW"),
    ]
    assert police.unparsed == [] and police.segments == []
    # No end given: it drops off after POLICE_MAX_AGE (our default), not AlertDC's 12 hours.
    assert police.end == police.published + dc.POLICE_MAX_AGE


def test_a_crime_alert_that_closes_no_road_is_still_dropped_unread() -> None:
    assert "alertdc-91003" not in advisories()
    assert dc.alertdc_kind("Crime Alert 3rd District (PSA 301-308)", []) is None
    assert dc.alertdc_kind("[AlertDC] Road Closures / Police Activity (P St, NW)", []) == "police"
    assert dc.alertdc_kind("[AlertDC] Road Closure / Vehicle Crash (Naylor Road, SE)", []) == (
        "traffic"
    )


def test_a_police_item_with_no_closure_that_reads_is_not_kept() -> None:
    page = (
        PAGE.replace("15th and P Street NW (Eastbound)", "nearby streets")
        .replace("14th and P Street NW (Westbound)", "and others")
        .replace("15th and Q Street NW", "as needed")
    )
    assert "alertdc-91001" not in {a.advisory_id for a in dc.parse_alertdc(page, NOW)}


def test_a_police_closure_ends_at_its_reopening_or_its_age() -> None:
    assert "alertdc-91001" not in advisories(NOW + dc.POLICE_MAX_AGE)
    reopened = PAGE.replace(
        "<tbody>",
        """<tbody><tr><td class="head">11/12/2026 9:00 AM</td><td class="head"><b>
        <a href="/NRss/RssFeed/AlertDetails/91004">[AlertDC] Final Update: Road Closures /
        Police Activity - Shooting Investigation (15th and P Streets, NW)</a></b><br />
        [AlertDC] All roads have reopened.</td></tr>""",
        1,
    )
    assert "alertdc-91001" not in {a.advisory_id for a in dc.parse_alertdc(reopened, NOW)}


@pytest.mark.parametrize(
    "line, corner",
    [
        ("15th and P Street NW (Eastbound)", ("15th Street NW", "P Street NW")),
        ("14th Street and P Street, NW", ("14th Street NW", "P Street NW")),
        ("the intersection of 15th and Q Streets NW", ("15th Street NW", "Q Street NW")),
        ("Georgia Avenue and Missouri Avenue, NW", ("Georgia Avenue NW", "Missouri Avenue NW")),
        ("14th St & P St NW", ("14th St NW", "P St NW")),
        ("There is a vehicle crash at Georgia Ave and Missouri Ave NW.", None),
        ("Please use caution and alternate routes", None),
        ("K Street NW between 14th and 15th Streets", None),
        ("15th and P Street NW until 6:00 PM", None),
    ],
)
def test_a_junction_closure_is_read(line, corner) -> None:
    assert dc.parse_corner(line) == corner


def test_the_area_keeps_its_margin_round_every_point() -> None:
    ring = dc.area_ring([P15, P14, Q15], dc.POLICE_MARGIN_M)
    assert ring[0] == ring[-1] and len(ring) >= 8
    lat0 = P15[1]
    xy = [wz._xy(lon, lat, lat0) for lon, lat in ring]
    for point in (P15, P14, Q15):
        at = wz._xy(point[0], point[1], lat0)
        assert wz._in_ring(at, xy)
        assert wz._distance_to_line(at, xy) >= dc.POLICE_MARGIN_M - 1.0


def police_zone() -> wz.Zone:
    police = advisories()["alertdc-91001"]
    return dc.area_zone(police, 0, [P15, P14, Q15], dc.POLICE_MARGIN_M, "15th St & P St NW")


def test_a_police_area_says_only_police_activity_and_where() -> None:
    zone = police_zone()
    assert zone.area and zone.kind == wz.CLOSED and zone.on_foot is True
    assert zone.title == "Police activity: streets closed near 15th St & P St NW"
    words = json.dumps(zone.to_json())
    assert not any(word in words for word in INCIDENT_WORDS)
    assert wz.Zone.from_json(zone.to_json()) == zone


# --- Routing round it -----------------------------------------------------------------

# A ride north up 15th St NW, through the area.
THROUGH = [[-77.0353, 38.9000 + i * 0.001] for i in range(25)]
# A ride north up 18th St NW, about 0.6 mi west: never in it.
BESIDE = [[-77.0416, 38.9000 + i * 0.001] for i in range(25)]


def test_a_route_through_the_area_is_on_it_and_one_beside_it_is_not() -> None:
    zone = police_zone()
    (passage,) = wz.along(THROUGH, [zone])
    # It enters about 300 m before 15th & P and leaves about 300 m past 15th & Q.
    assert 700 < passage.from_m < 850 and 1450 < passage.to_m < 1600
    assert wz.along(BESIDE, [zone]) == []


def test_the_router_leaves_out_the_whole_area() -> None:
    zone = police_zone()
    plan = wz.for_plan([zone], NOW, [THROUGH[0], THROUGH[-1]], {"alertdc": "current"}, now=NOW)
    assert plan.excluded == [zone]
    assert plan.exclude == [[list(p) for p in zone.line]]


def test_a_ride_that_starts_or_ends_in_the_area_is_warned_not_sent_round() -> None:
    zone = police_zone()
    for points in ([P15, THROUGH[-1]], [THROUGH[0], Q15]):
        plan = wz.for_plan([zone], NOW, points, {"alertdc": "current"}, now=NOW)
        assert plan.excluded == [] and plan.unexcluded == [zone]


# --- Placing, and AlertDC every minute ------------------------------------------------


class Net:
    def __init__(self, page: str = PAGE, fail: bool = False) -> None:
        self.page = page
        self.fail = fail
        self.asked: list[str] = []

    def __call__(self, url, timeout, headers) -> bytes:
        self.asked.append(url)
        if self.fail:
            raise workzones.FeedError("HTTP 503")
        assert "hsema" in url, url
        return self.page.encode()


class Placer:
    """Each junction where it is; 15th and P has a second, far-off candidate."""

    JUNCTIONS = {
        ("15th Street NW", "P Street NW"): [P15, [-77.0353, 38.8500]],
        ("14th Street NW", "P Street NW"): [P14],
        ("15th Street NW", "Q Street NW"): [Q15],
        ("Georgia Avenue NW", "Missouri Avenue NW"): [GEORGIA],
    }

    def __init__(self) -> None:
        self.calls = 0

    def corner_points(self, a, b):
        self.calls += 1
        return self.JUNCTIONS.get((a, b))

    def segment_line(self, segment):
        raise AssertionError("no segments here")


def no_sleep(_s: float) -> None:
    pass


def stored() -> dict:
    return BikeshareFeedCache.objects.get(key=sources.KEY).payload["feeds"]["alertdc"]


@pytest.fixture(autouse=True)
def _fresh():
    workzones.forget()
    yield
    workzones.forget()


@pytest.mark.django_db
def test_police_closures_become_one_wide_area_and_a_crash_corner_a_small_one() -> None:
    sources.refresh_fast(Net(), no_sleep, lambda: NOW, Placer())
    alertdc = stored()
    zones = {z["id"]: wz.Zone.from_json(z) for z in alertdc["zones"]}
    police, crash = zones["alertdc-91001-area0"], zones["alertdc-91002-area0"]
    assert police.margin_m == dc.POLICE_MARGIN_M and crash.margin_m == dc.CORNER_MARGIN_M
    assert crash.title == "Georgia Ave & Missouri Ave NW closed"
    # 15th and P's far-off candidate is not taken: the one near the other two junctions is.
    lat0 = P15[1]
    ring = [wz._xy(lon, lat, lat0) for lon, lat in police.line]
    assert wz._in_ring(wz._xy(P15[0], P15[1], lat0), ring)
    assert not wz._in_ring(wz._xy(-77.0353, 38.8500, lat0), ring)
    assert alertdc["notices"] == []
    kept = json.dumps(BikeshareFeedCache.objects.get(key=sources.KEY).payload)
    assert not any(word in kept for word in INCIDENT_WORDS)


@pytest.mark.django_db
def test_alertdc_is_read_again_only_where_its_page_changed() -> None:
    placer = Placer()
    sources.refresh_fast(Net(), no_sleep, lambda: NOW, placer)
    first = stored()
    calls = placer.calls
    later = NOW + timedelta(minutes=1)
    assert sources.refresh_fast(Net(), no_sleep, lambda: later, placer) == (
        "closures: alertdc unchanged"
    )
    again = stored()
    assert again["checked_at"] == later.isoformat() and again["read_at"] == NOW.isoformat()
    assert again["zones"] == first["zones"] and placer.calls == calls
    # A changed page is read at once; an unchanged one again after FAST_REREAD_S.
    changed = PAGE.replace("Please use alternate routes.", "Use other routes.")
    line = sources.refresh_fast(Net(changed), no_sleep, lambda: later, placer)
    assert line.startswith("closures: alertdc 2 closures")
    reread = NOW + timedelta(seconds=sources.FAST_REREAD_S + 60)
    assert "unchanged" not in sources.refresh_fast(Net(changed), no_sleep, lambda: reread, placer)


@pytest.mark.django_db
def test_the_two_tasks_keep_each_others_sources() -> None:
    """The fifteen-minute refresh leaves AlertDC out, and writes back only what it read, so a
    minute's AlertDC read made while it ran is not undone."""
    sources.refresh_fast(Net(), no_sleep, lambda: NOW, Placer())
    BikeshareFeedCache.objects.filter(key=sources.KEY).update(
        payload={
            "feeds": {
                **BikeshareFeedCache.objects.get(key=sources.KEY).payload["feeds"],
                "mpd": {"read_at": NOW.isoformat(), "zones": [], "notices": []},
            }
        }
    )
    feeds = {"mpd": {"read_at": "x", "zones": [], "notices": []}}
    sources._save(feeds, {"mpd"}, [], NOW)
    kept = BikeshareFeedCache.objects.get(key=sources.KEY).payload["feeds"]
    assert kept["mpd"]["read_at"] == "x" and kept["alertdc"]["zones"]
    assert sources.ALERTDC not in [s for s in sources.wanted() if s not in sources.FAST], (
        "the fifteen-minute refresh never reads AlertDC"
    )


# --- The review of #1175 --------------------------------------------------------------


def test_junctions_listed_for_anything_but_a_closure_are_not_closed() -> None:
    page = PAGE.replace(
        "[AlertDC] MPD reports the following road closure due to a vehicle crash:",
        "[AlertDC] Traffic signals are out at the following intersections:",
    ).replace("Road Closure / Vehicle Crash", "Traffic Signal Outage")
    outage = {a.advisory_id: a for a in dc.parse_alertdc(page, NOW)}.get("alertdc-91002")
    assert outage is None or outage.corners == []
    said = PAGE.replace(
        "[AlertDC] MPD reports the following road closure due to a vehicle crash:"
        "&#xA;&#x2022;&#x9;",
        "[AlertDC] ",
    ).replace(
        "Georgia Avenue and Missouri Avenue, NW",
        "Georgia Avenue and Missouri Avenue, NW is closed.",
    )
    crash = {a.advisory_id: a for a in dc.parse_alertdc(said, NOW)}["alertdc-91002"]
    assert [(c.a, c.b) for c in crash.corners] == [("Georgia Avenue NW", "Missouri Avenue NW")]


def test_a_police_reopening_titled_its_own_way_ends_the_area() -> None:
    reopened = PAGE.replace(
        "<tbody>",
        """<tbody><tr><td class="head">11/12/2026 9:00 AM</td><td class="head"><b>
        <a href="/NRss/RssFeed/AlertDetails/91005">[AlertDC] Update: Police Activity
        (15th and P Streets, NW) - Roads Reopened</a></b><br />
        [AlertDC] All roads have reopened following the police investigation.</td></tr>""",
        1,
    )
    found = {a.advisory_id for a in dc.parse_alertdc(reopened, NOW)}
    assert "alertdc-91001" not in found and "alertdc-91005" not in found


def test_a_police_area_does_not_link_the_alert_itself() -> None:
    assert advisories()["alertdc-91001"].url is None
    assert advisories()["alertdc-91002"].url.endswith("/AlertDetails/91002")


def test_a_rider_by_the_area_is_still_sent_round_its_closed_junctions() -> None:
    zone = police_zone()
    # Starting a block from 15th & P, inside the wide area: its closed junctions are left out.
    start = [P15[0], P15[1] - 0.0015]
    plan = wz.for_plan([zone], NOW, [start, THROUGH[-1]], {"alertdc": "current"}, now=NOW)
    assert plan.excluded == [zone]
    (ring,) = plan.rings[zone.zone_id]
    lat0 = P15[1]
    xy = [wz._xy(lon, lat, lat0) for lon, lat in ring]
    assert wz._in_ring(wz._xy(P15[0], P15[1], lat0), xy)
    assert not wz._in_ring(wz._xy(start[0], start[1], lat0), xy)
    # Starting at the closed junction itself: warned of, not left out.
    plan = wz.for_plan([zone], NOW, [P15, THROUGH[-1]], {"alertdc": "current"}, now=NOW)
    assert plan.excluded == [] and plan.unexcluded == [zone]


@pytest.mark.django_db
def test_an_unchanged_page_does_not_change_what_the_route_cache_keys_on() -> None:
    sources.refresh_fast(Net(), no_sleep, lambda: NOW, Placer())
    later = NOW + timedelta(minutes=1)
    sources.refresh_fast(Net(), no_sleep, lambda: later, Placer())
    kept = stored()
    assert kept["read_at"] == NOW.isoformat() and kept["checked_at"] == later.isoformat()
    # Still current long after the last read, as it was checked a minute ago.
    status = sources.load(
        BikeshareFeedCache.objects.get(key=sources.KEY).payload, NOW + timedelta(minutes=50)
    )[2]
    assert status["alertdc"] == "stale"
    status = sources.load(
        BikeshareFeedCache.objects.get(key=sources.KEY).payload, later + timedelta(minutes=10)
    )[2]
    assert status["alertdc"] == "current"


@pytest.mark.django_db
def test_the_stamp_changes_when_an_area_grows(monkeypatch) -> None:
    zone = police_zone()
    bigger = wz.Zone.from_json(
        {**zone.to_json(), "line": [list(p) for p in dc.area_ring([P15, P14, Q15, GEORGIA], 305)]}
    )
    snaps = iter([workzones.Snapshot(zones=[zone]), workzones.Snapshot(zones=[bigger])])
    monkeypatch.setattr(workzones, "snapshot", lambda: next(snaps))
    assert workzones.closures_stamp(NOW) != workzones.closures_stamp(NOW)


# --- Protests (Stephen 2026-11-13) ----------------------------------------------------

PROTEST_PAGE = (
    PAGE.replace(
        "Road Closures / Police Activity - Shooting Investigation",
        "Road Closures / Police Activity",
    )
    .replace(
        "Due to a shooting investigation, MPD reports",
        "Due to a First Amendment demonstration, MPD reports",
    )
    .replace(" Suspect described as armed.", "")
)


def test_a_protest_closure_is_an_ordinary_closure_not_a_wide_area() -> None:
    protest = {a.advisory_id: a for a in dc.parse_alertdc(PROTEST_PAGE, NOW)}["alertdc-91001"]
    assert not protest.police
    assert [(c.a, c.b) for c in protest.corners] == [
        ("15th Street NW", "P Street NW"),
        ("14th Street NW", "P Street NW"),
        ("15th Street NW", "Q Street NW"),
    ]
    # Before: the same item with a shooting in it is still a police area.
    assert advisories()["alertdc-91001"].police


def test_a_protest_with_any_violence_word_is_still_a_police_area() -> None:
    page = PROTEST_PAGE.replace("Please use alternate", "Several arrests. Please use alternate")
    assert {a.advisory_id: a for a in dc.parse_alertdc(page, NOW)}["alertdc-91001"].police
    assert dc.is_peaceful_protest("Road Closures / Police Activity (vigil)", "Barricades on K St")
    assert not dc.is_peaceful_protest("Police Activity (rally)", "Shots fired near the rally")
    assert not dc.is_peaceful_protest("Road Closures / Police Activity", "Closed until March 3")
