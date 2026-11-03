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


def test_the_two_difficulty_scales_are_kept_with_no_line_of_their_own() -> None:
    """Kept so the panel and the hover card can say which scale set a trail's level (the
    owner, 2026-10-28; `singletrack.mtb_scale_words`), and said nowhere else."""
    kept = trail_facts.facts({"mtb:scale": "2", "mtb:scale:imba": "3", "highway": "path"})
    assert kept == {"mtb:scale": "2", "mtb:scale:imba": "3"}
    assert trail_facts.rows(kept) == []


def test_a_one_way_trail_says_so_and_which_way_it_is_drawn() -> None:
    """The owner, 2026-11-03: "One way should keep it's one way" and "Make that clear when
    clicking on it too"."""
    assert trail_facts.facts({"oneway": "yes", "highway": "path"}) == {"oneway": "yes"}
    assert trail_facts.one_way({"oneway": "yes"}) == "forward"
    assert trail_facts.one_way({"oneway": "-1"}) == "backward"
    # oneway:bicycle wins: "no" opens a walkers' one-way to bikes both ways.
    assert trail_facts.one_way({"oneway": "yes", "oneway:bicycle": "no"}) is None
    assert trail_facts.one_way({"oneway:bicycle": "yes"}) == "forward"
    assert trail_facts.facts({"oneway:bicycle": "-1"}) == {"oneway:bicycle": "-1"}
    assert trail_facts.one_way({"oneway:bicycle": "-1"}) == "backward"
    # Bikes barred one way is one-way for a bike.
    assert trail_facts.one_way({"bicycle:backward": "no"}) == "forward"
    assert trail_facts.one_way({"bicycle:forward": "no", "oneway": "no"}) == "backward"
    for both in ({"oneway": "no"}, {"oneway": "alternating"}, {}, None):
        assert trail_facts.one_way(both) is None
    assert trail_facts.rows({"oneway": "yes"}) == [("oneway", "One way", trail_facts.ONE_WAY_WORDS)]
    assert trail_facts.rows({"oneway": "no"}) == []
