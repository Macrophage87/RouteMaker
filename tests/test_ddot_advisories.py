"""Closures from DDOT's project traffic advisories (v0.12.4, `routemaker.ddot_advisories`): the
owner, 2026-10-25, "maybe use these advisories for DC ... somehow the conneticut avenue
deckover was missed". Read by hand into a file, routed round like any DC closure, gone after
their last day; and the watcher's reading of a project's advisories page."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from routemaker import ddot_advisories as advisories
from routemaker import workzones as wz
from routemaker.ridetime import ZONE

PAGE = Path(__file__).parent / "data" / "closures" / "ddot-advisories-page.json"
DATA = json.loads(advisories.GEODATA.read_text())
CLOSURES, UPDATED = advisories.parse(DATA)
BY_ID = {c.closure_id: c for c in CLOSURES}
# The District's box, a little wide.
WEST, SOUTH, EAST, NORTH = -77.13, 38.78, -76.90, 39.00


def local(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE).astimezone(UTC)


def real(now: datetime) -> list[wz.Zone]:
    return advisories.real_zones(now, CLOSURES)


class TestTheFile:
    def test_every_closure_is_whole_and_in_the_district(self) -> None:
        assert len(BY_ID) == len(CLOSURES) > 0
        date.fromisoformat(UPDATED)
        for c in CLOSURES:
            assert c.first_day <= c.last_day, c.closure_id
            assert c.posted <= c.last_day, c.closure_id
            assert c.page.startswith("https://") and c.advisory.startswith("https://")
            assert c.road and c.reason and c.lines, c.closure_id
            for line in c.lines:
                for lon, lat in line:
                    assert WEST < lon < EAST and SOUTH < lat < NORTH, c.closure_id

    def test_every_advisory_used_is_marked_seen(self) -> None:
        seen = set(DATA["seen"])
        assert {c.advisory for c in CLOSURES} <= seen

    def test_the_deckover_and_the_tr_bridge_trail_are_closed(self) -> None:
        deckover = BY_ID["connave-deckover"]
        assert deckover.first_day == date(2025, 9, 23)
        assert len(deckover.lines) == 2  # both service lanes, Q Street to Dupont Circle
        trail = BY_ID["tr-bridge-trail"]
        assert (trail.first_day, trail.last_day) == (date(2026, 9, 21), date(2027, 9, 30))
        block = BY_ID["connave-1600-nb"]
        assert (block.first_day, block.last_day) == (date(2026, 8, 31), date(2026, 11, 3))


class TestTheReminders:
    """Audit 2026-10-29: a closure on a guessed last day dropped out silently, and a file never
    looked old. `scripts/ddot_advisories.py watch` prints these."""

    def test_a_guessed_last_day_within_30_days_is_a_reminder(self) -> None:
        nb = BY_ID["connave-1600-nb"]  # "about eight weeks", through 2026-11-03
        assert nb.end_estimated
        assert advisories.reminders("DDOT", [nb], "2026-10-25", date(2026, 10, 1)) == []
        (line,) = advisories.reminders("DDOT", [nb], "2026-10-25", date(2026, 10, 5))
        assert "2026-11-03 by estimate" in line
        # Gone once it is past, and never for a last day the release gives.
        assert advisories.reminders("DDOT", [nb], "2026-10-25", date(2026, 11, 4)) == []
        firm = advisories.Closure(**{**nb.__dict__, "end_estimated": False})
        assert advisories.reminders("DDOT", [firm], "2026-10-25", date(2026, 10, 5)) == []

    def test_a_file_not_updated_in_45_days_is_stale(self) -> None:
        assert not advisories.stale("2026-10-25", date(2026, 12, 9))
        assert advisories.stale("2026-10-25", date(2026, 12, 10))
        assert advisories.stale("", date(2026, 10, 25))
        (line,) = advisories.reminders("DDOT", [], "2026-10-25", date(2026, 12, 10))
        assert "not updated since 2026-10-25" in line

    def test_a_stale_file_says_so_in_its_small_print(self) -> None:
        from core import workzones

        assert workzones.stale_note(advisories.SOURCE) == (
            " This source was last read more than 45 days ago."
        )


class TestZones:
    def test_in_force_until_the_end_of_the_last_day_then_gone(self) -> None:
        ids = {z.zone_id for z in real(local(2026, 11, 3, 23, 59))}
        assert "ddot_advisory-connave-1600-nb-0" in ids
        ids = {z.zone_id for z in real(local(2026, 11, 4, 0, 0))}
        assert "ddot_advisory-connave-1600-nb-0" not in ids
        assert "ddot_advisory-connave-deckover-0" in ids

    def test_a_closure_routed_round_and_said_as_a_dc_heads_up(self) -> None:
        now = local(2026, 10, 25, 12, 0)
        zone = next(z for z in real(now) if z.zone_id == "ddot_advisory-connave-1600-nb-0")
        assert zone.kind == wz.CLOSED and zone.source == advisories.SOURCE
        assert not wz.possible(zone)  # a closure, never a "may close" permit
        assert zone.source in wz.CLOSURE_SOURCES
        assert zone.url == BY_ID["connave-1600-nb"].page
        assert wz.when_text(zone, now, False) == "Closed through Nov 3"
        assert wz.citation(zone) == "Source: DDOT project traffic advisory, through Nov 3."
        assert wz.source_text(zone) == "DDOT project traffic advisory, Sep 8"


class TestThePage:
    def test_a_dated_heading_title_and_button_page(self) -> None:
        entries = advisories.page_entries(json.loads(PAGE.read_text()))
        assert len(entries) == 9
        first = entries[0]
        assert first.day == date(2026, 9, 8)
        assert first.title.startswith("1600 Block Service Road of NB Connecticut Avenue NW")
        assert first.link == "https://app.box.com/s/o8lsvn311o6o8mcac9rxl9q6guaognny"
        assert [e.day for e in entries] == sorted((e.day for e in entries), reverse=True)
        assert not any("Download" in e.title or "Advisories" in e.title for e in entries)

    def test_a_table_page(self) -> None:
        html = (
            "<table><tr><td><h5>Temporary Lane Closures on Connecticut Avenue N.W.</h5></td>"
            "<td><h5>Monday, August 14, 2023 through Friday, August 18, 2023</h5></td>"
            '<td><a href="https://example.org/a">View</a></td></tr>'
            "<tr><td><h5>Eastbound Lanes Detour on Ordway St NW</h5></td>"
            '<td><h5>January 31, 2023</h5></td><td><a href="https://example.org/b">View</a>'
            "</td></tr></table>"
        )
        entries = advisories.page_entries({"values": {"cards": [{"markdown": html}]}})
        assert [(e.day, e.title) for e in entries] == [
            (
                date(2023, 8, 14),
                "Temporary Lane Closures on Connecticut Avenue N.W. Monday, August 14, 2023"
                " through Friday, August 18, 2023",
            ),
            (date(2023, 1, 31), "Eastbound Lanes Detour on Ordway St NW January 31, 2023"),
        ]

    def test_a_weekly_report_is_dated_by_its_first_day(self) -> None:
        html = (
            "Accordion October 2026 Description Date Download Document "
            "Weekly Progress Report 10/12/2026 - 10/18/2026"
            '<a href="https://example.org/r">View</a>'
        )
        (entry,) = advisories.page_entries({"markdown": html})
        assert entry.day == date(2026, 10, 12)
        assert entry.title == "Weekly Progress Report 10/12/2026 - 10/18/2026"

    def test_only_the_unseen_since_a_day_are_new(self) -> None:
        entries = advisories.page_entries(json.loads(PAGE.read_text()))
        assert advisories.unseen(entries, set(DATA["seen"])) == []
        new = advisories.unseen(entries, set(), since=date(2026, 7, 1))
        assert [e.day for e in new] == [date(2026, 9, 8), date(2026, 7, 7)]
        undated = advisories.Entry(None, "Project map", "https://example.org/m")
        assert advisories.unseen([undated], set(), since=date(2026, 7, 1)) == []
        banner = advisories.Entry(None, "Pedestrian Trail Closure", "https://example.org/t")
        assert advisories.unseen([banner], set(), since=date(2026, 7, 1)) == [banner]


@pytest.mark.django_db
class TestTheSnapshot:
    @pytest.fixture(autouse=True)
    def _real(self, monkeypatch):
        from core import workzones

        monkeypatch.setattr(advisories, "zones", advisories.real_zones)
        workzones.forget()
        yield
        workzones.forget()

    def test_the_snapshot_holds_them_and_a_route_along_one_is_told(self) -> None:
        from core import saved_route_alerts, workzones

        now = local(2026, 10, 25, 12, 0)
        snap = workzones.snapshot(now)
        assert snap.status[advisories.SOURCE] == workzones.CURRENT
        assert snap.read_at[advisories.SOURCE] == advisories.updated()
        assert any(z.source == advisories.SOURCE for z in snap.zones)

        line = [list(p) for p in BY_ID["connave-1600-nb"].lines[0]]
        found = workzones.closures_on(line, at=now, now=now)
        (row,) = [r for r in found["closures"] if r["source_key"] == advisories.SOURCE]
        assert row["road"] == BY_ID["connave-1600-nb"].road
        assert saved_route_alerts._until(row["end"], row["source_key"]) == ("through Nov 3, 2026")
