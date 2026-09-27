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
