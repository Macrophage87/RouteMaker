"""A map of more than one area (`routemaker.coverage`): the owner, 2026-11-23, a
Southwest Florida map beside DC to Baltimore. Each area is its own box; a point in
either is covered, the land between them is not, and no route spans the two."""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from pydantic import ValidationError

from core.api import RouteIn
from pipeline import run, source, states
from routemaker import coverage
from routemaker.stress import FL_URBAN_DEFAULT_MPH, statutory_default_mph

HOME = tuple(settings.COVERAGE_BBOX)
FLORIDA = tuple(settings.SOUTHWEST_FLORIDA_BBOX)
BOTH = {"dc-baltimore": HOME, "southwest-florida": FLORIDA}

WHITE_HOUSE = (-77.0365, 38.8977)
BONITA_SPRINGS = (-81.7787, 26.3398)
NAPLES = (-81.7948, 26.1420)
BETWEEN = (-81.6557, 30.3322)  # Jacksonville: inside the rectangle around both, in neither


@pytest.fixture
def two_areas(settings):
    settings.COVERAGE_AREAS = BOTH
    return settings


def test_the_default_map_is_the_home_area_alone() -> None:
    assert settings.COVERAGE_AREAS == {"dc-baltimore": HOME}
    assert coverage.boxes() == [HOME]


def test_southwest_florida_reaches_sarasota_and_shark_valley() -> None:
    for lon, lat in (
        BONITA_SPRINGS,
        NAPLES,
        (-81.8723, 26.6406),  # Fort Myers
        (-81.9495, 26.5629),  # Cape Coral
        (-82.0906, 26.9762),  # Port Charlotte
        (-81.4171, 26.4187),  # Immokalee
        (-81.7184, 25.9412),  # Marco Island
        (-82.5307, 27.3364),  # Sarasota
        (-82.5484, 27.2667),  # Siesta Key
        (-81.3851, 25.8573),  # Everglades City
        (-81.0828, 25.8960),  # Big Cypress, Oasis Visitor Center
        (-80.7670, 25.7578),  # Shark Valley visitor center
        (-80.7660, 25.6890),  # Shark Valley observation tower
    ):
        assert coverage.in_box(FLORIDA, lon, lat), (lon, lat)


def test_a_point_is_covered_in_either_area_and_not_between(two_areas) -> None:
    assert coverage.area_of(*WHITE_HOUSE) == "dc-baltimore"
    assert coverage.area_of(*BONITA_SPRINGS) == "southwest-florida"
    assert coverage.area_of(*BETWEEN) is None
    assert coverage.in_box(coverage.envelope(), *BETWEEN)


def test_one_area_refuses_points_in_two(two_areas) -> None:
    assert coverage.one_area([BONITA_SPRINGS, NAPLES]) == "southwest-florida"
    assert coverage.one_area([WHITE_HOUSE, BONITA_SPRINGS]) is None
    assert coverage.one_area([BETWEEN]) is None


def test_a_route_in_florida_is_taken_and_one_to_dc_refused(two_areas) -> None:
    RouteIn(points=[list(BONITA_SPRINGS), list(NAPLES)], preset="default")
    with pytest.raises(ValidationError):
        RouteIn(points=[list(BETWEEN), list(BETWEEN)], preset="default")
    with pytest.raises(ValidationError):
        RouteIn(points=[list(WHITE_HOUSE), list(BONITA_SPRINGS)], preset="default")


def test_a_florida_route_is_refused_while_the_map_has_only_home() -> None:
    with pytest.raises(ValidationError):
        RouteIn(points=[list(BONITA_SPRINGS), list(NAPLES)], preset="default")


@pytest.mark.django_db
def test_coverage_serves_one_polygon_per_area(client, two_areas) -> None:
    body = client.get("/api/coverage").json()
    assert body["geometry"]["type"] == "MultiPolygon"
    rings = [polygon[0] for polygon in body["geometry"]["coordinates"]]
    assert [(r[0][0], r[0][1], r[2][0], r[2][1]) for r in rings] == [HOME, FLORIDA]


def test_the_polygon_file_holds_each_area() -> None:
    feature = json.loads(coverage.polygon_geojson([HOME, FLORIDA]))
    assert feature["geometry"]["type"] == "MultiPolygon"
    assert len(feature["geometry"]["coordinates"]) == 2


def test_the_clip_takes_a_polygon_file_for_two_areas(tmp_path) -> None:
    class Context:
        coverage_polygon = None
        coverage_bbox = HOME
        coverage_areas = (HOME,)

    assert run.clip_region(Context, tmp_path) == HOME
    Context.coverage_areas = (HOME, FLORIDA)
    path = run.clip_region(Context, tmp_path)
    assert path == tmp_path / run.AREAS_POLYGON_NAME
    assert json.loads(path.read_text())["geometry"]["type"] == "MultiPolygon"
    assert source.clip_command(tmp_path / "m.pbf", tmp_path / "c.pbf", path)[-5:-3] == [
        "--polygon",
        str(path),
    ]


def test_florida_is_downloaded_only_with_its_area() -> None:
    assert not any("florida" in url for url in source.geofabrik_extracts())
    both = source.geofabrik_extracts(("dc-baltimore", "southwest-florida"))
    assert both[:4] == source.GEOFABRIK_EXTRACTS
    assert both[4].endswith("/us/florida/florida-latest.osm.pbf")


def test_florida_is_a_covered_state_with_its_area() -> None:
    assert "FL" not in states.covered_states()
    assert states.covered_states(("dc-baltimore", "southwest-florida"))[-1] == "FL"


class TestFloridaLaw:
    """Fla. Stat. 316.183(2): 30 mph in a business or residence district, 55 elsewhere."""

    def test_the_statutory_defaults(self) -> None:
        assert statutory_default_mph({}, "FL", urban=True, divided=False) == 30.0
        assert statutory_default_mph({}, "FL", urban=True, divided=True) == 30.0
        assert statutory_default_mph({}, "FL", urban=False, divided=False) == 55.0

    def test_urban_minor_roads_read_at_30(self) -> None:
        for highway in ("residential", "unclassified", "tertiary"):
            assert FL_URBAN_DEFAULT_MPH[highway] == 30.0


def test_a_hop_in_another_area_is_left_out(two_areas) -> None:
    body = RouteIn(
        points=[list(WHITE_HOUSE), [-77.03, 38.90]],
        preset="default",
        novice_hop=[list(BONITA_SPRINGS), list(NAPLES)],
    )
    assert body.novice_hop is None


def test_a_track_between_two_areas_is_refused(two_areas) -> None:
    from core import map_match

    with pytest.raises(map_match.TrackProblem):
        map_match.checked_points([list(WHITE_HOUSE), list(BONITA_SPRINGS)])


def test_a_florida_tile_is_clipped_to_floridas_box(two_areas) -> None:
    from core import stress_tiles
    from core.tile_cache import tile_index

    x, y = tile_index(*BONITA_SPRINGS, 10)
    assert not stress_tiles.outside_coverage(10, x, y)
    bounds = stress_tiles.tile_bounds(10, x, y)
    assert coverage.box_meeting(*bounds) == FLORIDA
    x, y = tile_index(*BETWEEN, 10)
    assert stress_tiles.outside_coverage(10, x, y)


def test_place_search_is_fenced_to_the_area_of_its_bias_point(two_areas) -> None:
    from core import geocode

    assert geocode._bbox_param(BONITA_SPRINGS) == ",".join(map(str, FLORIDA))
    assert geocode._bbox_param(WHITE_HOUSE) == ",".join(map(str, HOME))
    assert geocode._bbox_param(None) == ",".join(map(str, coverage.envelope()))


def test_elevation_is_fetched_for_each_area() -> None:
    from pipeline import elevation

    class Context:
        coverage_bbox = HOME
        other_areas = (FLORIDA,)
        coverage_areas = property(lambda self: (self.coverage_bbox, *self.other_areas))

    stems = {t.stem for box in Context().coverage_areas for t in elevation.tiles_covering(*box)}
    assert "N26W082" in stems and "N38W077" in stems
