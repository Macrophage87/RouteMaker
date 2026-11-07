"""Closures from the Fairfax County Park Authority's Park Alerts (v0.22.0, `routemaker.fcpa`): the
owner, 2026-11-07, "There's a closure on the cross county trail. See where this is posted and how
it was missed." Read by hand into a file once the owner confirms, routed round, gone after their
last day; `scripts/fcpa_alerts.py watch` lists the page's items not yet read."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from routemaker import fcpa
from routemaker import workzones as wz
from routemaker.ddot_advisories import parse
from routemaker.ridetime import ZONE

# Fairfax County, a little wide.
WEST, SOUTH, EAST, NORTH = -77.54, 38.6, -77.04, 39.06

# The Park Alerts page's shape (2026-11-06): menus are lists too; the alert's body is one list
# item a park, its name in bold, some with a nested list.
PAGE = """
<nav><ul><li><a href="/parks">Parks</a></li><li>Trails</li></ul></nav>
<article class="alert-notification"><div class="content">
<time datetime="2026-11-06T19:00:00Z">Fri, 11/06/2026 - 2:00 pm</time>
<div class="field field--name-body field--type-text-with-summary"><h2>Facility Updates</h2><ul>
<li><strong>Lake Accotink Park: </strong>The bridge near the marina is temporarily closed for
repairs. Weather permitting, the bridge will repaired and reopen by Friday, Nov. 13.</li>
<li><strong>South Run Rec Center: </strong>The following areas will be closed:<ul>
<li>Upper Level: Monday, Nov. 2-Thursday, Nov. 12</li><li>Lower Level: Nov. 13-23</li></ul></li>
<li><strong>Pimmit View Park:</strong> The bridge at the end of Storm Dr. will remain closed
until further notice for repairs.</li>
</ul></div></div></article>
<footer><ul><li>Contact us</li></ul></footer>
"""

# A made-up closure of the Cross County Trail's wooden bridge by the Lake Accotink marina, and a
# route over it, north-west along the trail.
BRIDGE = [[-77.21602, 38.79432], [-77.2163, 38.79443]]
CLOSURE = {
    "id": "accotink-marina-bridge",
    "project": "Lake Accotink Park",
    "page": fcpa.PAGE,
    "posted": "2026-11-06",
    "road": "Cross County Trail bridge by the Lake Accotink marina",
    "on_foot": True,
    "reason": "Closed for repairs.",
    "first_day": "2026-11-06",
    "last_day": "2026-11-13",
    "lines": [BRIDGE],
}
RIDDEN = [[-77.2154, 38.79408], *BRIDGE, [-77.21785, 38.79693]]


def local(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE).astimezone(UTC)


def real(now: datetime) -> list[wz.Zone]:
    closures, _ = parse({"updated": "2026-11-07", "closures": [CLOSURE]})
    return fcpa.real_zones(now, closures)


class TestTheFile:
    def test_every_closure_is_whole_and_in_fairfax(self) -> None:
        data = json.loads(fcpa.GEODATA.read_text())
        closures, updated = parse(data)
        date.fromisoformat(updated)
        assert isinstance(data["seen"], list)
        assert len({c.closure_id for c in closures}) == len(closures)
        for c in closures:
            assert c.first_day <= c.last_day, c.closure_id
            assert c.page.startswith("https://") and c.road and c.reason and c.lines
            for line in c.lines:
                for lon, lat in line:
                    assert WEST < lon < EAST and SOUTH < lat < NORTH, c.closure_id


class TestTheAlerts:
    def test_each_park_is_one_item_and_the_menus_are_not_read(self) -> None:
        items = fcpa.alert_items(PAGE)
        assert [i.park for i in items] == [
            "Lake Accotink Park",
            "South Run Rec Center",
            "Pimmit View Park",
        ]
        assert items[0].text.startswith("Lake Accotink Park: The bridge near the marina")
        assert "Lower Level: Nov. 13-23" in items[1].text  # a nested list stays in its item

    def test_trail_items_come_first_and_read_ones_drop_out(self) -> None:
        items = fcpa.alert_items(PAGE)
        assert [i.trail for i in items] == [True, False, True]
        fresh = fcpa.unseen(items, set())
        assert [i.park for i in fresh] == [
            "Lake Accotink Park",
            "Pimmit View Park",
            "South Run Rec Center",
        ]
        assert fcpa.unseen(items, {i.key for i in items}) == []

    def test_an_edited_item_is_listed_again(self) -> None:
        before = fcpa.alert_items(PAGE)
        after = fcpa.alert_items(PAGE.replace("Friday, Nov. 13", "Friday, Nov. 20"))
        (fresh,) = fcpa.unseen(after, {i.key for i in before})
        assert fresh.park == "Lake Accotink Park" and "Nov. 20" in fresh.text

    def test_a_page_with_no_alert_body_has_no_items(self) -> None:
        assert fcpa.alert_items("<html><ul><li>Parks</li></ul></html>") == []


class TestZones:
    def test_in_force_through_the_last_day_then_gone(self) -> None:
        assert real(local(2026, 11, 13, 23))
        assert real(local(2026, 11, 14, 0, 0)) == []

    def test_routed_round_and_told_as_a_closure_from_the_park_alerts(self) -> None:
        now = local(2026, 11, 7, 11, 40)
        (zone,) = real(now)
        assert zone.zone_id == "fcpa-accotink-marina-bridge-0"
        assert zone.kind == wz.CLOSED and zone.source == fcpa.SOURCE and zone.on_foot is True
        assert not wz.possible(zone) and zone.source in wz.CLOSURE_SOURCES
        assert zone.url == fcpa.PAGE
        assert wz.when_text(zone, now, False) == "Closed through Nov 13"
        assert wz.source_text(zone) == "Fairfax County Park Authority park alert, Nov 6"

    def test_a_route_over_it_runs_along_it(self) -> None:
        passages = wz.along(RIDDEN, real(local(2026, 11, 7, 11, 40)))
        assert [p.zone.zone_id for p in passages] == ["fcpa-accotink-marina-bridge-0"]


@pytest.mark.django_db
def test_the_snapshot_holds_them_and_names_the_source(monkeypatch) -> None:
    from core import workzones

    now = local(2026, 11, 7, 11, 40)
    monkeypatch.setattr(fcpa, "zones", lambda when, closures=None: real(when))
    workzones.forget()
    try:
        snap = workzones.snapshot(now)
        assert snap.status[fcpa.SOURCE] == workzones.CURRENT
        assert snap.read_at[fcpa.SOURCE] == fcpa.updated()
        assert "fcpa-accotink-marina-bridge-0" in {z.zone_id for z in snap.zones}
    finally:
        workzones.forget()
