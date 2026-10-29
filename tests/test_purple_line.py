"""Closures from the Purple Line's construction updates (v0.13.0, `routemaker.purple_line`): the
owner, 2026-10-27, "Bonifant street is closed for major construction. see why it's missed". Read
by hand into a file, routed round, gone after their last day."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from routemaker import purple_line
from routemaker import workzones as wz
from routemaker.ddot_advisories import parse
from routemaker.ridetime import ZONE

DATA = json.loads(purple_line.GEODATA.read_text())
CLOSURES, UPDATED = parse(DATA)
BY_ID = {c.closure_id: c for c in CLOSURES}
# Montgomery and Prince George's along the line, a little wide.
WEST, SOUTH, EAST, NORTH = -77.12, 38.93, -76.86, 39.02
# Bonifant St's junctions: Ramsey Ave, Dixon Ave, Georgia Ave.
RAMSEY, DIXON, GEORGIA = -77.02916, -77.02796, -77.0266
# A made-up route through the closure: north from Ripley St, west along Bonifant St from Dixon
# Ave, north up Ramsey Ave.
RIDDEN = [
    [DIXON, 38.99293],
    [DIXON, 38.99338],
    [-77.02888, 38.99337],
    [RAMSEY, 38.99337],
    [RAMSEY, 38.99398],
]


def local(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE).astimezone(UTC)


def real(now: datetime) -> list[wz.Zone]:
    return purple_line.real_zones(now, CLOSURES)


class TestTheFile:
    def test_every_closure_is_whole_and_on_the_line(self) -> None:
        assert len(BY_ID) == len(CLOSURES) > 0
        date.fromisoformat(UPDATED)
        for c in CLOSURES:
            assert c.first_day <= c.last_day, c.closure_id
            assert c.page.startswith("https://") and c.advisory.startswith("https://")
            assert c.road and c.reason and c.lines, c.closure_id
            for line in c.lines:
                for lon, lat in line:
                    assert WEST < lon < EAST and SOUTH < lat < NORTH, c.closure_id

    def test_bonifant_is_closed_ramsey_to_georgia_through_dixon(self) -> None:
        bonifant = BY_ID["bonifant-west"]
        lons = [lon for line in bonifant.lines for lon, _ in line]
        assert min(lons) == RAMSEY and max(lons) == GEORGIA
        # Each line's ends stay open (TRIM_M), so the lines overlap past Dixon Ave: its
        # junction is closed.
        assert any(
            line[0][0] < DIXON < line[-1][0]
            and wz.line_m([line[0], (DIXON, line[0][1])]) > wz.TRIM_M
            and wz.line_m([(DIXON, line[0][1]), line[-1]]) > wz.TRIM_M
            for line in bonifant.lines
        )


class TestZones:
    def test_in_force_until_the_end_of_the_last_day_then_gone(self) -> None:
        assert "purple_line-bonifant-west-0" in {z.zone_id for z in real(local(2027, 3, 31, 23))}
        assert real(local(2027, 4, 1, 0, 0)) == []

    def test_a_closure_routed_round_and_told_as_a_road_closed(self) -> None:
        now = local(2026, 10, 27, 7, 28)
        zones = real(now)
        zone = zones[0]
        assert zone.kind == wz.CLOSED and zone.source == purple_line.SOURCE
        assert not wz.possible(zone)
        assert zone.source in wz.CLOSURE_SOURCES
        assert zone.url == purple_line.PAGE
        assert wz.when_text(zone, now, False) == "Closed through Mar 31, 2027"  # next year (P11)
        assert wz.source_text(zone) == "Purple Line construction update, Jul 24"
        assert all(wz.polygon(z) for z in zones)

    def test_a_route_through_it_runs_along_it(self) -> None:
        passages = wz.along(RIDDEN, real(local(2026, 10, 27, 7, 28)))
        assert [p.zone.zone_id for p in passages] == ["purple_line-bonifant-west-0"]


@pytest.mark.django_db
class TestTheSnapshot:
    @pytest.fixture(autouse=True)
    def _real(self, monkeypatch):
        from core import workzones

        monkeypatch.setattr(purple_line, "zones", purple_line.real_zones)
        workzones.forget()
        yield
        workzones.forget()

    def test_the_snapshot_holds_them_and_a_route_along_one_is_told(self) -> None:
        from core import workzones

        now = local(2026, 10, 27, 7, 28)
        snap = workzones.snapshot(now)
        assert snap.status[purple_line.SOURCE] == workzones.CURRENT
        assert snap.read_at[purple_line.SOURCE] == purple_line.updated()
        found = workzones.closures_on(RIDDEN, at=now, now=now)
        (row,) = [r for r in found["closures"] if r["source_key"] == purple_line.SOURCE]
        assert row["road"] == BY_ID["bonifant-west"].road
