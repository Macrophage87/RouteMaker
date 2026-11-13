"""Location-dependent checks at places spread over the map: city, suburb and country, in DC,
Maryland, Virginia and West Virginia (the owner, 2026-11-04), and a few places outside it."""

from __future__ import annotations

import pytest
from places import INSIDE, OUTSIDE, params

from core import accounts, report_log, street_photo, weather
from core.api import RouteIn


def test_the_places_cover_every_setting_and_state() -> None:
    settings_seen = {p["setting"] for p in INSIDE}
    states = {p["names"]["state"] for p in INSIDE}
    assert settings_seen == {"urban", "suburban", "rural"}
    assert {"District of Columbia", "Maryland", "Virginia", "West Virginia"} <= states
    for setting in settings_seen:
        assert sum(p["setting"] == setting for p in INSIDE) >= 4, setting


@pytest.mark.parametrize("place", params(INSIDE))
def test_a_place_inside_the_map_is_covered_everywhere_it_is_asked(place) -> None:
    lon, lat = place["lon"], place["lat"]
    assert accounts._inside(lon, lat)
    assert street_photo.in_area(lon, lat)
    assert weather.inside_coverage([[lon, lat, 0]]) == [[lon, lat, 0]]
    RouteIn(points=[[lon, lat], [lon + 0.01, lat + 0.01]], preset="default")


@pytest.mark.parametrize("place", params(OUTSIDE))
def test_a_place_outside_the_map_is_refused_everywhere_it_is_asked(place) -> None:
    lon, lat = place["lon"], place["lat"]
    assert not accounts._inside(lon, lat)
    assert not street_photo.in_area(lon, lat)
    assert weather.inside_coverage([[lon, lat, 0]]) == []
    with pytest.raises(ValueError, match="outside the area this map covers"):
        RouteIn(points=[[lon, lat], [lon + 0.01, lat + 0.01]], preset="default")


@pytest.mark.parametrize("place", params(INSIDE))
def test_the_district_s_own_rules_apply_in_the_district_only(place) -> None:
    """DC's boundary (the 311 log's) is right in and out of town."""
    lon, lat = place["lon"], place["lat"]
    assert report_log.in_dc(lon, lat) is place["dc"]


@pytest.mark.parametrize("place", params(INSIDE))
def test_a_problem_report_goes_to_the_place_s_own_311(place) -> None:
    names = place["names"]
    found = report_log.jurisdiction(names["state"], names["county"], names["city"])
    assert found == place["report311"]
