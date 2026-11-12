"""Trail closures from the park agencies (v0.26.0, `routemaker.park_alerts`): NOVA Parks (the
W&OD), NPS's C&O Canal conditions page (by milepost) and Anne Arundel County's closings list.
Backlog 2026-11-12, item 8. Read by hand into a file, routed round, gone after their last day;
`scripts/park_alerts.py watch` lists what is not yet read. Pages are made up in each site's shape
as read live on 2026-11-12."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from routemaker import park_alerts as pa
from routemaker import workzones as wz
from routemaker.ddot_advisories import parse
from routemaker.ridetime import ZONE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import park_alerts as script  # noqa: E402

# The map's box (settings.COVERAGE_BBOX), the C&O's last miles included.
WEST, SOUTH, EAST, NORTH = -78.05, 38.2, -76.02, 39.72

NOVA_HOME = """
<nav><a href="/parks">Parks</a></nav>
<div class="copy"><a href="/alert/wod-november-17-24-trail-detours-falls-church" class="t-c-black">
<span>Parks</span> - W&amp;OD -November 17-24. Trail Detours in Falls Church</a></div>
<div class="copy"><a href="/alert/wod-through-spring-2028-sterling-blvd">Sterling</a></div>
<div class="copy"><a href="/alert/wod-november-17-24-trail-detours-falls-church">again</a></div>
"""

NOVA_ALERT = """
<main id="main-content"><article id="node-1" class="node node--type-notification">
<h1 class="page-title">Park Alerts</h1>
<h2 class="page-title">
  W&amp;OD -November 17-24. Trail Detours in Falls Church at Grove Ave, N. West St, Park Ave.
</h2>
<div class="clearfix text-formatted field field--name-body field--type-text-with-summary">
<p><span>Crosswalk work where N. West Street crosses the W&amp;OD Trail begins November 17,
2026 and lasts about 1 week. Expect detour signage.</span></p></div>
</article></main>
<h2>Park Alerts</h2><a href="/alert/other">Parks - Something else</a>
"""

CHOH_PAGE = """
<h2>Towpath and Park Conditions</h2><p>C&amp;O Canal NHP stretches 184.5 miles.</p>
<h3>Milepost 0&ndash;25</h3><ul>
<li><h4>Georgetown Area (MP 0.4)</h4><ul>
<li><span style="color:#27ae60;">Open</span>, <a href="/x">Georgetown Visitor Center</a></li>
<li><span style="color:#c0392b;">Closed for the Season</span>, Georgetown Canal Boat</li>
</ul></li>
<li><h4>Little Falls (MP 4.7)</h4><ul>
<li><span style="color:#f39c12;">Work Alert</span>, DC Water repairs near Little Falls.
<ul><li><a href="https://parkplanning.nps.gov/x">Repair the interceptor</a></li></ul></li>
</ul></li>
<li><h4>Taylors Landing (MP 80.9)</h4><ul>
<li><span style="color:#c0392b;"> </span><span style="color:#27ae60;">Open</span><span>, </span>Boat
ramp</li></ul></li>
<li><h4>McMahons Mill Area (MP 88.1)</h4><ul>
<li><span style="color:#e67e22;">High Water Detour</span> - During high water the towpath between
milepost 84.4 and milepost 89.1 may be covered in water.</li></ul></li>
<li><h4>Dam No. 5 (MP 106.8)</h4><ul>
<li><span style="color:#e67e22;">Towpath Detour</span><span>, </span>Miles 106 - 106.8, Detour
from the towpath across the canal to Dam No. 5 Road.</li>
<li><span style="color:#c0392b;">Closed</span>, Parking lot.</li>
</ul></li></ul>
<h2>Weather</h2><p>Forecasts.</p>
"""

AA_PAGE = """
<article><div class="alerts-list-paragraph">
<div class="zn-alert-list-entry zn-warning"><div class="container"><div class="zn-stage">
<div class="zn-badge"><div class="h5"><span class="badge text-uppercase warning">
 Closed <span></div></div>
<h3 class="zn-title"><p>B&amp;A Trail Closure</p></h3>
<div class="zn-body"><p>The B&amp;A Trail will be closed from the 100 Bridge to Jumpers Hole
Road from November 18 to November 20.</p></div></div></div></div>
<div class="zn-alert-list-entry zn-warning"><div class="container"><div class="zn-stage">
<div class="zn-badge"><div class="h5"><span class="badge text-uppercase warning">Closed<span>
</div></div><h3 class="zn-title"><p>Sawmill Skate Park Closure</p></h3>
<div class="zn-body"><p>The skate park is closed for enhancements.</p></div></div></div></div>
</div></article>
"""

# A made-up closure of the C&O towpath from mile 30 to mile 31 (White's Ferry way).
TOWPATH = pa.towpath_lines(30, 31)
CLOSURE = {
    "id": "choh-mp30-31",
    "project": "NPS, C&O Canal",
    "page": pa.CHOH.page,
    "posted": "2026-11-12",
    "road": "C&O Canal towpath, mile 30 to 31",
    "on_foot": True,
    "reason": "Towpath closed for repairs.",
    "first_day": "2026-11-16",
    "last_day": "2026-11-20",
    "lines": TOWPATH,
}


def local(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE).astimezone(UTC)


def real(now: datetime) -> list[wz.Zone]:
    closures, _ = parse({"updated": "2026-11-12", "closures": [CLOSURE]})
    return pa.real_zones(now, closures)


class TestTheFile:
    def test_every_closure_is_whole_and_inside_the_map(self) -> None:
        data = json.loads(pa.GEODATA.read_text())
        closures, updated = parse(data)
        date.fromisoformat(updated)
        assert isinstance(data["seen"], dict) and set(data["seen"]) <= set(pa.AGENCIES)
        assert len({c.closure_id for c in closures}) == len(closures)
        for c in closures:
            assert c.first_day <= c.last_day, c.closure_id
            assert c.project in {a.name for a in pa.AGENCIES.values()}, c.closure_id
            assert c.page.startswith("https://") and c.road and c.reason and c.lines
            for line in c.lines:
                for lon, lat in line:
                    assert WEST < lon < EAST and SOUTH < lat < NORTH, c.closure_id


class TestNovaParks:
    def test_each_alert_the_home_page_links_once(self) -> None:
        assert pa.nova_links(NOVA_HOME) == [
            "https://www.novaparks.com/alert/wod-november-17-24-trail-detours-falls-church",
            "https://www.novaparks.com/alert/wod-through-spring-2028-sterling-blvd",
        ]

    def test_an_alert_is_its_title_and_its_body_not_the_page_heading(self) -> None:
        item = pa.nova_item("https://www.novaparks.com/alert/x", NOVA_ALERT)
        assert item.place.startswith("W&OD -November 17-24. Trail Detours in Falls Church")
        assert item.text.startswith("Crosswalk work where N. West Street crosses the W&OD Trail")
        assert "Something else" not in item.text
        assert item.trail and item.link == "https://www.novaparks.com/alert/x"

    def test_a_page_with_no_title_is_no_item(self) -> None:
        assert pa.nova_item("https://www.novaparks.com/alert/x", "<main></main>") is None


class TestCAndOCanal:
    def test_only_states_other_than_open_with_the_places_mileposts(self) -> None:
        items = pa.choh_items(CHOH_PAGE)
        assert [(i.place, i.text.split(":")[0], i.miles) for i in items] == [
            ("Georgetown Area (MP 0.4)", "Closed for the Season", (0.4, 0.4)),
            ("Little Falls (MP 4.7)", "Work Alert", (4.7, 4.7)),
            (
                "McMahons Mill Area (MP 88.1)",
                "High Water Detour - During high water the towpath "
                "between milepost 84.4 and milepost 89.1 may be covered in water.",
                (84.4, 89.1),
            ),
            ("Dam No. 5 (MP 106.8)", "Towpath Detour", (106.0, 106.8)),
            ("Dam No. 5 (MP 106.8)", "Closed", (106.8, 106.8)),
        ]

    def test_a_nested_link_stays_in_its_line(self) -> None:
        little_falls = pa.choh_items(CHOH_PAGE)[1]
        assert little_falls.text.endswith("Repair the interceptor")

    def test_the_towpath_and_detours_are_trail_items_a_boat_or_a_lot_not(self) -> None:
        items = pa.choh_items(CHOH_PAGE)
        assert [i.trail for i in items] == [False, False, True, True, False]

    def test_the_towpath_between_two_mileposts(self) -> None:
        (line,) = pa.towpath_lines(30, 31)
        length = sum(pa._metres(a, b) for a, b in zip(line, line[1:], strict=False))
        assert abs(length - pa.MILE_M) < 30.0
        # Mile 30 is a little west of Edwards Ferry, mile 31 a little further.
        assert -77.48 < line[0][0] < -77.45 and -77.48 < line[-1][0] < -77.45

    def test_one_milepost_is_a_short_stretch_round_it(self) -> None:
        (line,) = pa.towpath_lines(4.7, 4.7)
        length = sum(pa._metres(a, b) for a, b in zip(line, line[1:], strict=False))
        assert 90.0 < length < 110.0

    def test_a_piece_boundary_adds_no_empty_line_and_a_reversed_range_reads_the_same(
        self,
    ) -> None:
        data = {
            "trails": [
                {
                    "n": "Chesapeake and Ohio Canal Trail",
                    "s": 0,
                    "l": [[-77.0, 39.0], [-77.01, 39.0]],
                },
                {
                    "n": "Chesapeake and Ohio Canal Trail",
                    "s": 1000,
                    "l": [[-77.02, 39.0], [-77.03, 39.0]],
                },
            ]
        }
        boundary = 1000 / pa.MILE_M
        lines = pa.towpath_lines(boundary - 0.2, boundary, data)
        assert len(lines) == 1 and all(len(set(map(tuple, line))) == len(line) for line in lines)
        assert pa.towpath_lines(boundary, boundary - 0.2, data) == lines

    def test_a_stretch_with_no_mile_line_has_no_line(self) -> None:
        data = {"trails": [{"n": "Chesapeake and Ohio Canal Trail", "s": 0, "l": [[-77, 39]]}]}
        assert pa.towpath_lines(12, 14, data) == []

    def test_the_script_says_how_much_it_covers(self, capsys) -> None:
        assert script.towpath(30, 31) == 0
        assert "cover 100%" in capsys.readouterr().err
        assert script.towpath(12, 14) == 1  # the mile lines have a gap there
        assert "draw it from the OpenStreetMap ways" in capsys.readouterr().err


class TestAnneArundel:
    def test_each_entry_with_its_badge(self) -> None:
        items = pa.aacounty_items(AA_PAGE)
        assert [(i.place, i.trail) for i in items] == [
            ("B&A Trail Closure", True),
            ("Sawmill Skate Park Closure", False),
        ]
        assert items[0].text.startswith("Closed: The B&A Trail will be closed")


class TestTheWatch:
    def pages(self, url: str) -> str:
        if url == pa.NOVA.page:
            return NOVA_HOME
        if "/alert/" in url:
            return NOVA_ALERT
        if url == pa.CHOH.page:
            return CHOH_PAGE
        return AA_PAGE

    def test_trail_items_first_then_marked_read(self, tmp_path, monkeypatch, capsys) -> None:
        file = tmp_path / "park-closures.json"
        file.write_text('{"updated": "2026-11-12", "closures": [], "seen": {}}\n')
        monkeypatch.setattr(pa, "GEODATA", file)
        pa._loaded.cache_clear()
        try:
            assert script.watch(list(pa.AGENCIES), True, self.pages) == 0
            out = capsys.readouterr().out
            assert "== NPS, C&O Canal: 2 new trail items, 3 other new" in out
            assert out.index("Miles 106 - 106.8") < out.index("(other)")
            seen = json.loads(file.read_text())["seen"]
            assert set(seen) == {"nova", "choh", "aacounty"} and len(seen["choh"]) == 5
            assert script.watch(list(pa.AGENCIES), False, self.pages) == 0
            assert "0 new trail items, 0 other new" in capsys.readouterr().out
        finally:
            pa._loaded.cache_clear()

    def test_a_page_that_answers_with_no_items_is_an_error(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(pa, "GEODATA", pa.GEODATA)
        assert script.watch(["choh"], False, lambda url: "<html></html>") == 1
        assert "layout changed" in capsys.readouterr().err


class TestZones:
    def test_in_force_through_the_last_day_then_gone(self) -> None:
        assert real(local(2026, 11, 20, 23))
        assert real(local(2026, 11, 21, 0, 0)) == []

    def test_routed_round_and_told_as_a_closure_from_a_park_agency(self) -> None:
        now = local(2026, 11, 17, 9, 0)
        (zone,) = real(now)
        assert zone.zone_id == "park_alert-choh-mp30-31-0"
        assert zone.kind == wz.CLOSED and zone.source == pa.SOURCE and zone.on_foot is True
        assert not wz.possible(zone) and zone.source in wz.CLOSURE_SOURCES
        assert zone.url == pa.CHOH.page
        assert wz.when_text(zone, now, False) == "Closed through Nov 20"
        assert wz.source_text(zone) == "Park agency trail alert, Nov 12"

    def test_a_ride_along_the_towpath_runs_along_it(self) -> None:
        ridden = pa.towpath_lines(29.5, 31.5)[0]
        passages = wz.along(ridden, real(local(2026, 11, 17, 9, 0)))
        assert [p.zone.zone_id for p in passages] == ["park_alert-choh-mp30-31-0"]


@pytest.mark.django_db
def test_the_snapshot_holds_them_and_names_the_source(monkeypatch) -> None:
    from core import workzones

    now = local(2026, 11, 17, 9, 0)
    monkeypatch.setattr(pa, "zones", lambda when, closures=None: real(when))
    workzones.forget()
    try:
        snap = workzones.snapshot(now)
        assert snap.status[pa.SOURCE] == workzones.CURRENT
        assert snap.read_at[pa.SOURCE] == pa.updated()
        assert "park_alert-choh-mp30-31-0" in {z.zone_id for z in snap.zones}
    finally:
        workzones.forget()
