"""A saved route's row figures (core.route_sketch; backlog 2026-11-12, Plan item 9): the sketch,
climb and quiet share Load route and My routes show, kept on the row and listed with it."""

from __future__ import annotations

import pytest
from test_accounts import ANSWER, LINE, addr, route_body, send, signed_in

from core import route_sketch
from core.models import SavedRoute

db = pytest.mark.django_db


def test_the_sketch_fits_the_box_north_up_and_keeps_its_ends() -> None:
    # A line running north-east: its start is bottom left, its end top right.
    out = route_sketch.sketch([[-77.05, 38.90], [-77.04, 38.905], [-77.03, 38.91]])
    assert out is not None
    assert all(0 <= v <= route_sketch.BOX for p in out for v in p)
    (sx, sy), (ex, ey) = out[0], out[-1]
    assert sx < ex and sy > ey
    # The longer side fills the box.
    assert max(p[0] for p in out) - min(p[0] for p in out) == route_sketch.BOX


def test_a_long_line_is_thinned_to_the_cap() -> None:
    import math

    # A 5,000-point wiggle (a GPX file): never more than MAX_POINTS, and no recursion limit.
    line = [[-77.0 + i * 1e-5, 38.9 + 0.002 * math.sin(i / 7)] for i in range(5000)]
    out = route_sketch.sketch(line)
    assert out is not None and 2 <= len(out) <= route_sketch.MAX_POINTS


def test_no_sketch_for_a_point_or_nothing() -> None:
    assert route_sketch.sketch(None) is None
    assert route_sketch.sketch([[-77.0, 38.9]]) is None
    assert route_sketch.sketch([[-77.0, 38.9], [-77.0, 38.9]]) is None


def test_quiet_is_levels_1_and_2_of_all_the_metres() -> None:
    answer = {
        "climb_m": 81.3,
        "stress_m": {"1": 300, "2": 480, "3": 120, "4": 0, "5": 0, "unknown": 100},
    }
    assert route_sketch.quiet_pct(answer) == 78
    assert route_sketch.climb_m(answer) == 81.3
    # A file's line has no answer: no climb or quiet share, said as unknown, never 0.
    assert route_sketch.figures(LINE, None)["climb_m"] is None
    assert route_sketch.figures(LINE, None)["quiet_pct"] is None


@db
class TestListed:
    def test_a_save_lists_its_figures(self) -> None:
        client, _user, csrf = signed_in()
        assert send(client, "post", "/api/me/routes", route_body(), csrf).status_code == 201
        row = client.get("/api/me/routes", **addr()).json()["routes"][0]
        figures = row["figures"]
        assert figures == route_sketch.figures(LINE, ANSWER)
        assert len(figures["sketch"]) >= 2

    def test_an_older_route_gets_its_figures_when_listed_without_a_new_date(self) -> None:
        client, user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        SavedRoute.objects.filter(pk=rid).update(figures=None)
        before = SavedRoute.objects.get(pk=rid).updated_at
        row = client.get("/api/me/routes", **addr()).json()["routes"][0]
        assert row["figures"]["sketch"]
        kept = SavedRoute.objects.get(pk=rid)
        assert kept.figures == row["figures"]
        assert kept.updated_at == before

    def test_a_new_version_makes_its_figures_again(self) -> None:
        client, _user, csrf = signed_in()
        rid = send(client, "post", "/api/me/routes", route_body(), csrf).json()["id"]
        longer = [*LINE, [-77.0101, 38.9101, 20.0]]
        r = send(client, "post", "/api/me/routes", route_body(line=longer, version_of=rid), csrf)
        assert r.status_code == 200, r.content
        assert SavedRoute.objects.get(pk=rid).figures["sketch"] == route_sketch.sketch(longer)
