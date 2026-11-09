"""The weekend graph's facility values (pipeline.run.facility_derived)."""

import pytest

from pipeline.run import facility_derived
from pipeline.variants import Variant

CLASSES = {1: "none", 2: "lane", 3: "path"}
CAR_FREE = {1: frozenset({"weekend"}), 2: frozenset({"weekday_rush"})}


def test_a_weekend_closure_is_a_path_on_the_weekend_graph_only():
    assert facility_derived(Variant.WEEKEND, 1, CLASSES, CAR_FREE) == {
        "facility": "path",
        "stress_tier": 1,
    }
    for variant in (Variant.STANDARD, Variant.EBIKE):
        assert facility_derived(variant, 1, CLASSES, CAR_FREE) == {"facility": "none"}


def test_a_closure_at_other_times_is_not():
    assert facility_derived(Variant.WEEKEND, 2, CLASSES, CAR_FREE) == {"facility": "lane"}


def test_mass_rides_graph_has_no_facility_even_at_the_weekend():
    for way in (1, 2, 3):
        assert facility_derived(Variant.NO_TRAIL, way, CLASSES, CAR_FREE) == {
            "facility_neutral": True
        }


@pytest.mark.parametrize("variant", [Variant.STANDARD, Variant.EBIKE, Variant.WEEKEND])
def test_an_unclassified_way_gets_nothing(variant):
    assert facility_derived(variant, 99, CLASSES, CAR_FREE) == {}


def test_the_weekend_graph_is_the_standard_graphs_twin():
    """Its OSM tags are the standard graph's (variants.inject)."""
    from pipeline.variants import inject

    tags = {"highway": "path", "electric_bicycle": "no"}
    assert inject(Variant.WEEKEND, tags, 7, frozenset(), frozenset()) == inject(
        Variant.STANDARD, tags, 7, frozenset(), frozenset()
    )
    barred = inject(Variant.WEEKEND, {"highway": "primary"}, 7, frozenset(), frozenset({7}))
    assert barred["bicycle"] == "no", "a mass-ride-only roadway is barred on it as on standard"


def test_the_route_reads_a_closure_only_where_the_graph_opens_it():
    # Hunt X1 (2026-11-08): the route's colours, breakdown and ranking read a timed closure as
    # a path in the plan's ride time on every graph; now only where the routed graph prices it
    # so (`core.routing.car_free_reading`), as `facility_derived` does for the weekend graph.
    from core.routing import NO_CAR_FREE_TIME, car_free_reading

    assert car_free_reading("weekend", "weekend") == "weekend"
    for graph in ("standard", "ebike", "paved", "offroad", "mtb", "no-trail"):
        assert car_free_reading("weekend", graph) == NO_CAR_FREE_TIME
    for when in ("weekday_rush", "weekday_offpeak", "night"):
        assert car_free_reading(when, "weekend") == NO_CAR_FREE_TIME
        assert car_free_reading(when, "standard") == NO_CAR_FREE_TIME
    assert car_free_reading("weekend", None) == "weekend", "outside a plan, as before"


# --- Road Bike's weekend graph (the owner, 2026-11-08: "Road bikes absolutely use those parkways
# on the weekends. It's probably their most common destination."; "New weekend graph") ---


def test_road_bikes_weekend_graph_reads_a_weekend_closure_as_a_path():
    """`Variant.PAVED_WEEKEND` is the paved graph plus the weekend graph's car-free reading."""
    assert facility_derived(Variant.PAVED_WEEKEND, 1, CLASSES, CAR_FREE) == {
        "facility": "path",
        "stress_tier": 1,
    }
    assert facility_derived(Variant.PAVED_WEEKEND, 2, CLASSES, CAR_FREE) == {"facility": "lane"}
    assert facility_derived(Variant.PAVED_WEEKEND, 99, CLASSES, CAR_FREE) == {}
    assert facility_derived(Variant.PAVED, 1, CLASSES, CAR_FREE) == {"facility": "none"}


def test_road_bikes_weekend_graph_keeps_the_paved_graphs_pricing_and_tags():
    from pipeline.variants import (
        OFFROAD_FAMILY,
        PAVED_GRAPHS,
        PAVED_WEEKEND_ROUTER,
        RESTART_OFFROAD_ROUTER,
        RESTART_ROUTERS,
        WEEKEND_GRAPHS,
        inject,
    )

    assert PAVED_GRAPHS == {Variant.PAVED, Variant.PAVED_WEEKEND}
    assert WEEKEND_GRAPHS == {Variant.WEEKEND, Variant.PAVED_WEEKEND}
    tags = {"highway": "path", "surface": "gravel"}
    assert inject(Variant.PAVED_WEEKEND, tags, 7, frozenset(), frozenset()) == inject(
        Variant.PAVED, tags, 7, frozenset(), frozenset()
    )
    # Behind the compose profile `offroad`, as the paved router is: never in a plain restart.
    assert Variant.PAVED_WEEKEND in OFFROAD_FAMILY
    assert PAVED_WEEKEND_ROUTER == "valhalla-paved-weekend"
    assert PAVED_WEEKEND_ROUTER in RESTART_OFFROAD_ROUTER
    assert PAVED_WEEKEND_ROUTER not in RESTART_ROUTERS


def test_the_route_reads_a_weekend_closure_on_road_bikes_weekend_graph():
    from core.routing import NO_CAR_FREE_TIME, car_free_reading

    assert car_free_reading("weekend", "paved-weekend") == "weekend"
    for when in ("weekday_rush", "weekday_offpeak", "night"):
        assert car_free_reading(when, "paved-weekend") == NO_CAR_FREE_TIME


def test_road_bikes_weekend_graph_falls_back_to_the_paved_graph():
    from core import routing

    assert routing.twin_fallback("paved-weekend") == "paved"
    for twin in ("weekend", "offroad", "mtb", "paved"):
        assert routing.twin_fallback(twin) == "standard"
    assert "paved-weekend" in routing.TWIN_VARIANTS
    assert "paved-weekend" not in routing.TRAIL_TOUCH_VARIANTS
