"""MORE links for a mountain-bike trail's page (routemaker.more_links; slice 6)."""

from __future__ import annotations

from routemaker import more_links


def test_a_named_trail_links_its_systems_page() -> None:
    link = more_links.link_for("Rosaryville Perimeter Trail")
    assert link == {
        "label": "Rosaryville State Park on MORE: trailheads, trail info and conditions",
        "url": "https://more-mtb.org/products/rosaryville-state-park",
        "system": "Rosaryville State Park",
    }


def test_any_of_the_names_may_place_it() -> None:
    assert more_links.system_for(None, "", "Lake Accotink Loop").slug == "lake-accotink"
    assert more_links.system_for("Loop 3", "Schaeffer Farm Trail").slug == "schaeffer-arms"


def test_whole_words_only() -> None:
    # "Wheatonville" is not Wheaton.
    assert more_links.system_for("Wheatonville Road") is None
    assert more_links.system_for("Wheaton Regional Park trail").name == "Wheaton Regional Park"


def test_the_longest_match_wins() -> None:
    assert more_links.system_for("Seneca Ridge Trail").slug == "seneca-ridge-trail-srt"
    assert more_links.system_for("Seneca Creek Greenway Trail").slug == "seneca-greenway"


def test_no_match_gives_the_general_link_never_a_guess() -> None:
    for names in ((), (None,), ("Loop 3",), ("",)):
        assert more_links.link_for(*names) == {
            "label": more_links.GENERAL_LABEL,
            "url": "https://more-mtb.org/collections/trails",
            "system": None,
        }


def test_every_system_is_one_link_on_mores_site() -> None:
    slugs = [s.slug for s in more_links.SYSTEMS]
    assert len(slugs) == len(set(slugs)), "one link per trail system"
    for system in more_links.SYSTEMS:
        assert system.url.startswith("https://more-mtb.org/products/")
        assert system.words and all(w == w.lower() for w in system.words)
