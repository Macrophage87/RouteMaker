"""A mountain-bike trail's own tags in words, for the road panel (the owner, 2026-10-19:
"should have information related to surface and the like on the map" and "The information
should be available when clicked on")."""

from __future__ import annotations

from routemaker import trail_facts


def test_only_the_kept_tags_are_kept_and_none_is_none() -> None:
    tags = {"highway": "path", "surface": "dirt", "width": " 1 ", "name": "Loop 3"}
    assert trail_facts.facts(tags) == {"surface": "dirt", "width": "1"}
    assert trail_facts.facts({"highway": "path", "surface": "  "}) is None


def test_a_long_value_is_cut() -> None:
    kept = trail_facts.facts({"surface": "x" * 200})
    assert kept is not None and len(kept["surface"]) == trail_facts.MAX_VALUE


def test_the_lines_in_order_with_us_units_first() -> None:
    kept = {
        "sac_scale": "mountain_hiking",
        "mtb:scale:uphill": "3",
        "trail_visibility": "bad",
        "width": "0.6",
        "smoothness": "very_bad",
        "surface": "ground;rock",
    }
    assert trail_facts.rows(kept) == [
        ("trail_surface", "Trail surface", "Dirt, rock"),
        ("smoothness", "Smoothness", "Very bumpy (a mountain bike)"),
        ("width", "Width", "2 ft (0.6 m)"),
        ("visibility", "Trail visibility", "Faint in places"),
        ("uphill", "Climbing", "Hard: steep or loose (3 of 5)"),
        ("hiking", "Hiking scale", "T2, mountain hiking"),
    ]


def test_widths_in_feet_and_metres() -> None:
    assert trail_facts.width_words("3 ft") == "3 ft (0.9 m)"
    assert trail_facts.width_words("2'6\"") == "2.5 ft (0.8 m)"
    assert trail_facts.width_words("4 m") == "13 ft (4.0 m)"
    assert trail_facts.width_words("narrow") is None
    assert trail_facts.width_words("0") is None


def test_an_unknown_surface_is_said_as_mapped_and_other_unknowns_are_left_out() -> None:
    kept = {"surface": "artificial_turf", "smoothness": "meh", "trail_visibility": "?"}
    assert trail_facts.rows(kept) == [("trail_surface", "Trail surface", "Artificial turf")]
    assert trail_facts.rows(None) == []
    assert trail_facts.rows({"mtb:scale:uphill": "9"}) == []
