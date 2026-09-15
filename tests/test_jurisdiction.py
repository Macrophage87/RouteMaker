"""Jurisdiction assignment, against real PostGIS geometry."""

from __future__ import annotations

import pytest
from django.contrib.gis.geos import LineString, MultiPolygon, Polygon
from django.db import connection

pytestmark = pytest.mark.django_db(transaction=True)


def box(west: float, east: float, south: float = 38.88, north: float = 38.92) -> MultiPolygon:
    return MultiPolygon(
        Polygon(((west, south), (east, south), (east, north), (west, north), (west, south)))
    )


@pytest.fixture
def authorities():
    from core.models import Jurisdiction

    Jurisdiction.objects.all().delete()
    # DC west of -77.00, Virginia east of it, on the police layer.
    Jurisdiction.objects.create(
        layer="police", name="MPD", state="DC", geometry=box(-77.05, -77.00)
    )
    Jurisdiction.objects.create(
        layer="police", name="Arlington County Police", state="VA", geometry=box(-77.00, -76.95)
    )
    # A small federal enclave straddling the line on the manager layer.
    Jurisdiction.objects.create(
        layer="manager",
        name="National Park Service",
        state="DC",
        is_federal_enclave=True,
        geometry=box(-77.005, -76.999),
    )
    Jurisdiction.objects.create(layer="row", name="DDOT", state="DC", geometry=box(-77.05, -77.00))
    yield
    Jurisdiction.objects.all().delete()


def test_way_wholly_inside_one_authority(authorities) -> None:
    from pipeline.jurisdiction import assign_way

    way = LineString((-77.04, 38.90), (-77.02, 38.90), srid=4326)
    police = [a for a in assign_way(way) if a.layer == "police"]
    assert [a.authority for a in police] == ["MPD"]
    assert police[0].fraction == pytest.approx(1.0, abs=0.01)


def test_way_straddling_a_line_reports_both_with_shares(authorities) -> None:
    """A way can straddle a boundary, so the tagger reports every authority with
    the share inside each rather than silently picking a winner."""
    from pipeline.jurisdiction import assign_way

    way = LineString((-77.02, 38.90), (-76.98, 38.90), srid=4326)
    police = {a.authority: a.fraction for a in assign_way(way) if a.layer == "police"}
    assert set(police) == {"MPD", "Arlington County Police"}
    assert police["MPD"] == pytest.approx(0.5, abs=0.05)


def test_all_three_layers_are_assigned(authorities) -> None:
    """The permit issuer is frequently not a police agency, so scoping this to
    police would leave it out."""
    from pipeline.jurisdiction import assign_way

    way = LineString((-77.004, 38.90), (-77.001, 38.90), srid=4326)
    assert {a.layer for a in assign_way(way)} == {"police", "manager", "row"}


def test_crossings_are_ordered_along_the_route(authorities) -> None:
    """Re-entering the District after a mile in Virginia is a second crossing,
    not a footnote on the first."""
    from pipeline.jurisdiction import route_crossings

    way = LineString((-77.04, 38.90), (-76.96, 38.90), srid=4326)
    crossings = route_crossings(way, "police")
    assert [c.authority for c in crossings] == ["MPD", "Arlington County Police"]
    assert crossings[0].start_m < crossings[1].start_m


def test_federal_enclave_flag_survives_to_the_crossing(authorities) -> None:
    """The flag is what exempts a short crossing from the length collapse, so it
    has to reach the crossing rather than stopping at the polygon."""
    from pipeline.crossings import collapse_short_crossings
    from pipeline.jurisdiction import route_crossings

    way = LineString((-77.04, 38.90), (-76.96, 38.90), srid=4326)
    manager = route_crossings(way, "manager")
    assert manager and manager[0].is_federal_enclave
    # Roughly 500 m, well under the tenth-of-a-mile collapse threshold.
    assert manager[0].length_m < 700
    assert collapse_short_crossings(manager) == manager


def test_boundary_streets_are_recognised() -> None:
    from pipeline.jurisdiction import is_boundary_street

    assert is_boundary_street("Western Avenue")
    assert not is_boundary_street("Connecticut Avenue")


def test_reentry_produces_two_crossings_not_a_phantom_one(authorities) -> None:
    """The earlier implementation located intersection pieces on the line with
    ST_LineLocatePoint, which is ambiguous once a route visits an area twice. On
    a real route it produced five crossings for two, two of them spanning tens of
    kilometres of a park the route barely clipped."""
    from pipeline.jurisdiction import route_crossings

    # West into VA, back into DC, out into VA again.
    way = LineString(
        (-77.02, 38.90), (-76.97, 38.90), (-77.02, 38.905), (-76.97, 38.905), srid=4326
    )
    va = [c for c in route_crossings(way, "police") if c.authority.startswith("Arlington")]
    assert len(va) == 2
    for crossing in va:
        assert crossing.length_m < 6_000, "no crossing may exceed the route's own scale"


def test_out_and_back_counts_both_traversals(authorities) -> None:
    """ST_Intersection dissolves coincident forward and return runs into one
    piece, halving the jurisdiction mileage that goes on a permit application."""
    from pipeline.jurisdiction import route_crossings

    # Out past the far edge of the Virginia box and back, so the polygon is
    # genuinely traversed twice. A turnaround *inside* the polygon would be one
    # continuous stay and correctly reported as one crossing.
    out_and_back = LineString((-77.02, 38.90), (-76.94, 38.90), (-77.02, 38.90), srid=4326)
    va = [c for c in route_crossings(out_and_back, "police") if c.authority.startswith("Arlington")]
    assert len(va) == 2, "both traversals must be reported"


def test_loop_starting_inside_a_polygon_has_no_wrap_around_crossing(authorities) -> None:
    """Normalising a wrap-around piece by sorting its endpoints turned 0.79-to-0
    into 0-to-0.79 and invented a crossing spanning most of the loop."""
    from pipeline.jurisdiction import route_crossings

    loop = LineString(
        (-77.02, 38.90),
        (-76.98, 38.90),
        (-76.98, 38.91),
        (-77.02, 38.91),
        (-77.02, 38.90),
        srid=4326,
    )
    total = sum(c.length_m for c in route_crossings(loop, "police"))
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(%s::geometry::geography)", [loop.ewkb])
        route_length = cursor.fetchone()[0]
    assert total <= route_length * 1.05, "crossings cannot exceed the route length"


def test_crossing_lengths_sum_to_the_route_length(authorities) -> None:
    """The number that goes on a permit application. Deriving positions from
    degree fractions of a metre length misplaced them by about four percent."""
    from pipeline.jurisdiction import route_crossings

    way = LineString((-77.04, 38.90), (-76.96, 38.90), srid=4326)
    crossings = route_crossings(way, "police")
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(%s::geometry::geography)", [way.ewkb])
        route_length = cursor.fetchone()[0]
    covered = sum(c.length_m for c in crossings)
    assert covered == pytest.approx(route_length, rel=0.02)
