from __future__ import annotations

import pytest

from pipeline.variants import Variant, inject, is_trail_class, variant_for


def test_standard_passes_tags_through() -> None:
    tags = {"highway": "residential"}
    assert inject(Variant.STANDARD, tags) == tags


def test_no_trail_drops_trail_class_ways() -> None:
    """Dropped rather than tagged inaccessible: a way tagged bicycle=no still
    occupies the graph and still lands in trace results."""
    assert inject(Variant.NO_TRAIL, {"highway": "cycleway"}) is None
    assert inject(Variant.NO_TRAIL, {"highway": "residential"}) is not None


def test_trail_class_ignores_the_bicycle_tag() -> None:
    """DC-area trails are tagged inconsistently, so a definition that consulted
    the bicycle tag would classify the same trail differently along its length."""
    assert is_trail_class({"highway": "path", "bicycle": "designated"})
    assert is_trail_class({"highway": "path", "bicycle": "no"})


def test_sidepath_bridges_count_as_trail_class() -> None:
    """Most Potomac and Anacostia crossings are bike-legal only by a sidepath;
    missing them would leave the no-trail variant thinking they are roadways.

    The id is a parameter, not a tag. The earlier version read `_osm_id` from the
    tag dict, which only this test ever set - a way read from a real PBF carries
    OSM's own tags and nothing else, so the lookup could never match in the
    pipeline while the test passed.
    """
    tags = {"highway": "trunk"}
    assert not is_trail_class(tags, 99)
    assert is_trail_class(tags, 99, frozenset({99}))
    assert not is_trail_class(tags, 98, frozenset({99}))


def test_ebike_bars_only_where_electric_bicycles_are_barred() -> None:
    barred = inject(Variant.EBIKE, {"highway": "path", "electric_bicycle": "no"})
    allowed = inject(Variant.EBIKE, {"highway": "path"})
    assert barred["bicycle"] == "no"
    assert "bicycle" not in allowed


def test_variant_selection_from_toggles() -> None:
    assert variant_for(allow_trails=True, ebike_rules=False) is Variant.STANDARD
    assert variant_for(allow_trails=True, ebike_rules=True) is Variant.EBIKE
    assert variant_for(allow_trails=False, ebike_rules=False) is Variant.NO_TRAIL


def test_exclusive_combination_is_refused_not_guessed() -> None:
    """The UI disables the combination and explains why; the pipeline refuses it
    rather than silently picking one."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        variant_for(allow_trails=False, ebike_rules=True)
