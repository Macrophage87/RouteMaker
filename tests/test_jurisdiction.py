"""Jurisdiction assignment, against real PostGIS geometry."""

from __future__ import annotations

import math

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


@pytest.mark.parametrize(
    "order", [("Aqueduct Trust", "Zenith Trust"), ("Zenith Trust", "Aqueduct Trust")]
)
def test_assignments_tied_on_share_are_ordered_by_name(order, authorities) -> None:
    """The tiebreaker `route_crossings` has, which this query did not.

    Two polygons covering a way equally is not exotic - a boundary running down
    the middle of a block puts two agencies on half of it each - and the order
    the rows come back in is not cosmetic. `authorities_for` keeps the largest
    share on each layer *whatever* its size, so where the tie is below
    `MIN_JURISDICTION_FRACTION` the first row back is the one authority the way
    is tagged with and the other is dropped. Without `j.name` that was whatever
    the plan produced, which here follows the order the rows were inserted in -
    so the same extract clipped twice could tag the same way with a different
    agency, and the parametrisation is the two insertion orders.
    """
    from core.models import Jurisdiction
    from pipeline.jurisdiction import assign_way
    from pipeline.run import MIN_JURISDICTION_FRACTION, authorities_for

    for name in order:
        Jurisdiction.objects.create(
            layer="manager", name=name, state="MD", geometry=box(-77.05, -77.00, 38.70, 38.74)
        )

    # A way whose ends sit in neither polygon: it runs south out of both, with a
    # twentieth of its length inside each - equal shares, both well under the
    # tenth `authorities_for` needs before it keeps a second authority.
    way = LineString((-77.03, 38.7002), (-77.01, 38.7002), (-77.01, 38.30), srid=4326)
    manager = [a for a in assign_way(way) if a.layer == "manager"]

    assert [a.authority for a in manager] == ["Aqueduct Trust", "Zenith Trust"]
    assert manager[0].fraction == pytest.approx(manager[1].fraction, abs=1e-9)
    assert manager[0].fraction < MIN_JURISDICTION_FRACTION, "the tie is below the threshold"
    assert authorities_for(manager, MIN_JURISDICTION_FRACTION) == {"Aqueduct Trust"}


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


@pytest.mark.parametrize(
    "name",
    [
        "Western Avenue",
        "Western Avenue Northwest",
        "Western Ave NW",
        # The abbreviated spellings the normaliser used to miss. OSM carries
        # both along each of these streets, so an exact match fired on part of
        # the length and not the rest - which is worse than not firing, because
        # the border inserter then fragments only the part it missed and the
        # crossing report shows entries into Montgomery County for a ride that
        # never left the curb.
        "Western Ave",
        "Eastern Ave NE",
        "Eastern Ave",
        "Southern Ave SE",
        "eastern ave se",
        # The `av` alternative, which no case reached: OSM carries "Western Av"
        # and "Eastern Av NE" on stretches of both streets, and deleting `av`
        # from `_STREET_TYPE` left the whole suite green while those stretches
        # went unmatched - the same partial firing, one abbreviation further in.
        "Western Av",
        "Eastern Av NE",
        "Southern Av.",
        "western av nw",
    ],
)
def test_boundary_streets_are_recognised(name: str) -> None:
    from pipeline.jurisdiction import is_boundary_street

    assert is_boundary_street(name)


@pytest.mark.parametrize(
    "name",
    [
        "Connecticut Avenue",
        "Connecticut Ave NW",
        # Normalising the street type must not turn an unrelated name into a
        # boundary street: it expands the abbreviation, it does not match on it.
        "Ave",
        "Av",
        "Western Street",
        # The abbreviation is expanded at the *end* of the name only, so a
        # street type in the middle of one is not a boundary street either.
        "Western Ave Park",
        "Western Ave Extended",
        None,
        "",
    ],
)
def test_other_streets_are_not(name: str | None) -> None:
    from pipeline.jurisdiction import is_boundary_street

    assert not is_boundary_street(name)


def test_the_match_is_on_the_name_alone_and_says_so() -> None:
    """Baltimore's Eastern Avenue answers true, and that is the accepted reading.

    There is no geometry test and no bounding box in `is_boundary_street`: any
    way in the extract carrying one of the three names matches, and Baltimore is
    inside the coverage box. Recorded as a test rather than only as a comment,
    because the cost is asymmetric and the asymmetry is the argument. The one
    consumer is `borders.find_state_crossings`, so a false match costs a border
    node not inserted on a street that crosses no state line; a false negative
    fragments a District boundary street into a string of stubs. Narrowing it
    would mean a geometry test here, and nothing needs one yet.

    If that changes - if a second consumer appears that acts on the name in a
    way a Baltimore street should not reach - this is the test that should stop
    it, by being rewritten rather than by silently continuing to pass.
    """
    from pipeline.jurisdiction import is_boundary_street

    assert is_boundary_street("Eastern Avenue"), "and nothing here knows which one"


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


def test_a_federal_enclave_that_overlaps_another_polygon_still_sorts_first(authorities) -> None:
    """The ORDER BY's enclave-first key, not alphabetising, decides which
    authority is primary where a federal enclave genuinely overlaps another
    polygon on the same layer - M-NCPPC's own land, inside which the Park
    Service holds a small federal enclave, the way it does at Rock Creek.

    Without `is_federal_enclave DESC NULLS LAST` the query falls back to
    `j.name` alone, and "M-NCPPC" alphabetises ahead of "National Park
    Service" - the wrong authority would become primary rather than `also`,
    and a crossing that changes which body issues the permit would be
    reported as the ordinary one.
    """
    from core.models import Jurisdiction
    from pipeline.jurisdiction import route_crossings

    Jurisdiction.objects.create(
        layer="manager", name="M-NCPPC", state="MD", geometry=box(-77.03, -77.01)
    )
    Jurisdiction.objects.create(
        layer="manager",
        name="National Park Service",
        state="DC",
        is_federal_enclave=True,
        geometry=box(-77.02, -77.015),
    )

    # Both endpoints sit inside the overlap of the two polygons, so the whole
    # route is one run naming both authorities.
    way = LineString((-77.018, 38.90), (-77.016, 38.90), srid=4326)
    crossings = route_crossings(way, "manager")

    assert len(crossings) == 1, crossings
    assert crossings[0].authority == "National Park Service"
    assert crossings[0].also_authority == "M-NCPPC"
    assert crossings[0].is_federal_enclave


def test_a_route_along_a_shared_boundary_reports_both_authorities(authorities) -> None:
    """A boundary street's centreline *is* the line, so its vertices sit on the
    shared edge of two polygons and both authorities apply along its length.

    Until this was carried through, `Crossing.also_authority` was a documented
    field with no producer: a ride on Eastern Avenue really does involve Prince
    George's County, and the report called the whole thing DC.
    """
    from pipeline.jurisdiction import route_crossings

    # Straight down the shared edge at -77.00, which both police polygons touch.
    along_the_line = LineString((-77.00, 38.890), (-77.00, 38.910), srid=4326)
    crossings = route_crossings(along_the_line, layer="police")

    assert crossings, "a route on the line is still inside an authority"
    shared = [c for c in crossings if c.also_authority]
    assert shared, "both authorities apply along a boundary street"
    named = {shared[0].authority, shared[0].also_authority}
    assert named == {"MPD", "Arlington County Police"}


def test_a_route_inside_one_authority_names_no_second(authorities) -> None:
    """The field is for a street that runs along a boundary, not for every route
    that ends near one."""
    from pipeline.jurisdiction import route_crossings

    inside = LineString((-77.04, 38.890), (-77.02, 38.910), srid=4326)
    crossings = route_crossings(inside, layer="police")
    assert crossings
    assert all(crossing.also_authority is None for crossing in crossings)


def test_clipping_a_neighbour_at_one_vertex_is_not_a_shared_run(authorities) -> None:
    """A run is reported as shared only where it is shared along its whole
    length; one vertex touching a neighbouring polygon at a corner is a route
    crossing a boundary, not a street running along one."""
    from pipeline.jurisdiction import route_crossings

    # Mostly inside DC, touching the shared edge only at its final vertex.
    grazing = LineString((-77.04, 38.900), (-77.00, 38.900), srid=4326)
    crossings = route_crossings(grazing, layer="police")
    dc_runs = [c for c in crossings if c.authority == "MPD"]
    assert dc_runs
    assert all(crossing.also_authority is None for crossing in dc_runs)


def test_a_run_that_leaves_the_boundary_stops_being_shared(authorities) -> None:
    """The case the first vertex alone cannot answer.

    Reading the shared authority off the vertex that opens a run is not enough:
    a route that starts on the line and turns away from it is on Eastern Avenue
    for one vertex and inside the District for the rest, and reporting the whole
    stretch as shared would put a county on a permit application that the ride
    never entered.
    """
    from pipeline.jurisdiction import route_crossings

    leaving = LineString((-77.00, 38.900), (-77.04, 38.900), srid=4326)
    crossings = route_crossings(leaving, layer="police")
    dc_runs = [c for c in crossings if c.authority == "MPD"]
    assert dc_runs
    assert all(crossing.also_authority is None for crossing in dc_runs)


def test_a_long_boundary_stretch_between_two_inland_legs_is_still_reported(authorities) -> None:
    """The discrimination the minimum makes, stated where it bites.

    A momentary shared vertex at an ordinary crossing is a transition and is
    folded into the leg it opens. A stretch that runs for blocks with a leg on
    either side is a boundary street, and absorbing it would report a ride down
    Eastern Avenue as DC end to end - which is the thing the field exists to
    prevent.
    """
    from pipeline.jurisdiction import route_crossings

    down_the_line = LineString(
        (-77.02, 38.890),
        (-77.00, 38.892),
        (-77.00, 38.908),
        (-77.02, 38.910),
        srid=4326,
    )
    crossings = route_crossings(down_the_line, layer="police")
    shared = [c for c in crossings if c.also_authority]
    assert len(shared) == 1, [
        (c.authority, c.also_authority, round(c.end_m - c.start_m)) for c in crossings
    ]
    assert shared[0].length_m > 1000, "the stretch along the line is most of the route"
    assert {shared[0].authority, shared[0].also_authority} == {"MPD", "Arlington County Police"}


# Metres per degree of longitude at this fixture's latitude, so a test can place
# a route a stated number of metres off the shared edge at -77.00.
METRES_PER_DEGREE_LON = 111_320.0 * math.cos(math.radians(38.90))
# And of latitude, so a shared stretch can be given a stated length.
METRES_PER_DEGREE_LAT = 111_320.0


def test_the_shared_boundary_constants_are_the_figures_the_module_argues_for() -> None:
    """Both were free. `SHARED_BOUNDARY_TOLERANCE_M` moved from 2.0 to 20.0 and
    `MIN_SHARED_RUN_M` from 50.0 to 5.0 with the whole suite green, because
    every case above is either a route *on* the line - centimetres from both
    polygons, which clears any tolerance - or one well inland, and every shared
    stretch in them is either one vertex long or over a kilometre. Neither
    figure had a case anywhere near it, so the two behavioural pins below stand
    on either side of each, and the figures themselves are typed in here the way
    `stress`'s Furth widths are.
    """
    from pipeline.jurisdiction import MIN_SHARED_RUN_M, SHARED_BOUNDARY_TOLERANCE_M

    assert SHARED_BOUNDARY_TOLERANCE_M == 2.0
    assert MIN_SHARED_RUN_M == 50.0


@pytest.mark.parametrize(
    ("offset_m", "shared"),
    [(0.5, True), (1.5, True), (3.0, False), (10.0, False)],
)
def test_the_tolerance_decides_how_far_off_the_line_is_still_the_line(
    authorities, offset_m: float, shared: bool
) -> None:
    """What the two metres buy, on either side of the figure.

    A boundary street's centreline *is* the line, so its vertices sit within
    centimetres of both polygons; a street a few metres inside the District is
    a District street and naming a Virginia authority on it would put a county
    on a permit application for a ride that never left DC. Widening the
    tolerance to 20 m - which the suite allowed - reaches the next street over.
    """
    from pipeline.jurisdiction import route_crossings

    lon = -77.00 - offset_m / METRES_PER_DEGREE_LON
    route = LineString((lon, 38.890), (lon, 38.910), srid=4326)
    crossings = route_crossings(route, layer="police")
    assert crossings
    named_both = [c for c in crossings if c.also_authority]
    assert bool(named_both) is shared, (
        offset_m,
        [(c.authority, c.also_authority) for c in crossings],
    )


@pytest.mark.parametrize(
    ("run_m", "reported"),
    [(20.0, False), (40.0, False), (120.0, True), (400.0, True)],
)
def test_the_minimum_run_separates_a_boundary_street_from_a_crossing(
    authorities, run_m: float, reported: bool
) -> None:
    """The other constant, on either side of its figure.

    Every ordinary boundary crossing puts a vertex within the tolerance of both
    sides, so without a minimum each one grows a short "both authorities" run in
    front of it and an out-and-back through one county reports four entries
    instead of two. A boundary street runs for blocks. The route here comes out
    of the District, runs along the line for `run_m`, and turns back inland, so
    the only thing varying between the cases is the length of the shared
    stretch.
    """
    from pipeline.jurisdiction import route_crossings

    half = run_m / 2 / METRES_PER_DEGREE_LAT
    route = LineString(
        (-77.02, 38.900 - half),
        (-77.00, 38.900 - half),
        (-77.00, 38.900 + half),
        (-77.02, 38.900 + half),
        srid=4326,
    )
    crossings = route_crossings(route, layer="police")
    shared = [c for c in crossings if c.also_authority]
    assert bool(shared) is reported, (
        run_m,
        [(c.authority, c.also_authority, round(c.end_m - c.start_m)) for c in crossings],
    )


def test_the_tagging_stage_owns_its_own_annotation_key(authorities, tmp_path) -> None:
    """`_jurisdictions` is the pipeline's key, not the source's.

    `read_ways` hands back whatever the PBF carried, and OSM accepts any key at
    all - so a way tagged `_jurisdictions=...` upstream arrives at this stage
    with the annotation already occupied. Defaulted rather than assigned, the
    stage kept the string the file carried and its own spatial assignment was
    dropped on the floor with nothing logged: the authority list a permit
    question is answered from would be a stranger's text.

    The other writer of this key, `apply_jurisdiction`, runs in a later stage
    (`Stage.APPLY_OVERRIDES` follows `Stage.TAG_JURISDICTIONS`), so an approved
    override is applied over this and is not what the guard protected.
    """
    from pipeline.extract import Way
    from pipeline.rebuild import Stage
    from pipeline.run import RebuildContext, build_handlers

    way = Way(
        osm_id=1,
        tags={"highway": "residential", "_jurisdictions": "Somewhere Else"},
        node_ids=[1, 2],
    )
    way.coordinates = [(-77.04, 38.90), (-77.02, 38.90)]
    way.located = [0, 1]

    context = RebuildContext(
        source_pbf=tmp_path / "source.osm.pbf",
        work_dir=tmp_path / "work",
        reference_dir=tmp_path / "reference",
        tiles_dir=tmp_path / "tiles",
    )
    context.ways = [way]
    context.ways_by_id = {way.osm_id: way}

    build_handlers(context, load_overrides=lambda: [])[Stage.TAG_JURISDICTIONS]()

    assigned = set(way.tags["_jurisdictions"].split(","))
    assert "Somewhere Else" not in assigned, (
        "a `_jurisdictions` key the source PBF carried survived the stage whose job is "
        "to compute it"
    )
    assert "MPD" in assigned, assigned


def test_the_stages_that_write_the_jurisdiction_annotation_are_in_this_order() -> None:
    """Stated because the assignment above depends on it: the override is the
    last word on an authority, and it is the last word by being applied after
    the stage that computes one."""
    from pipeline.rebuild import Stage

    order = list(Stage)
    assert order.index(Stage.TAG_JURISDICTIONS) < order.index(Stage.APPLY_OVERRIDES)
