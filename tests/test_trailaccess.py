"""NO-BIKE-PATHS tag rules (OWNER-DECISIONS 278, 280, 281, 291)."""

from __future__ import annotations

import pytest
from routemaker import trailaccess as ta
from routemaker.trailaccess import WayRoutes


def v(tags, routes=ta.NO_ROUTES, in_park=False):
    return ta.verdict({"highway": "path", **tags}, routes, in_park)


@pytest.mark.parametrize(
    "tags, reason",
    [
        ({"access": "private"}, "private"),
        ({"access": "permit"}, "private"),
        ({"access": "customers", "surface": "asphalt"}, "private"),
        ({"bicycle": "permit"}, "private"),
        ({"sac_scale": "hiking"}, "sac_scale"),
        ({"informal": "yes"}, "informal"),
        ({"foot": "designated"}, "foot_designated"),
        ({"trail_visibility": "bad"}, "trail_visibility"),
        ({"trail_visibility": "intermediate"}, "trail_visibility"),
        ({"surface": "dirt"}, "natural_surface"),
        ({"surface": "ground"}, "natural_surface"),
        ({"surface": "grass"}, "natural_surface"),
    ],
)
def test_the_tag_rules_close(tags, reason):
    assert v(tags) == reason


@pytest.mark.parametrize(
    "tags",
    [
        {"sac_scale": "hiking", "surface": "asphalt"},
        {"foot": "designated", "surface": "concrete"},
        {"trail_visibility": "bad", "surface": "paved"},
        {"surface": "gravel"},
        {"surface": "fine_gravel"},
        {"surface": "compacted"},
        {"surface": "dirt", "smoothness": "good"},
        {"surface": "dirt", "tracktype": "grade2"},
        {"surface": "dirt", "width": "2.5"},
        {"surface": "dirt", "mtb:scale": "0"},
        {"surface": "asphalt"},
        {},
    ],
)
def test_the_exemptions_keep_a_way(tags):
    """The last case is a plain path outside a park, kept (291(1))."""
    assert v(tags) is None


def test_a_plain_path_closes_only_inside_a_park():
    assert v({}, in_park=True) == "park_path"
    assert v({}) is None
    assert v({"surface": "asphalt"}, in_park=True) is None
    assert v({"smoothness": "intermediate"}, in_park=True) is None
    assert v({}, WayRoutes(bicycle_networks=frozenset({"lcn"})), in_park=True) is None


def test_hiking_route_members_close_unless_a_bicycle_route_holds_them():
    hiking = WayRoutes(hiking=True)
    assert v({}, hiking) == "hiking_route"
    assert v({"surface": "asphalt"}, hiking) is None
    both = WayRoutes(hiking=True, bicycle_networks=frozenset({"rcn"}))
    assert v({}, both) is None


def test_only_national_and_international_routes_keep_a_natural_surface():
    """The Cross County Trail is a regional route and holds its rough sections;
    the C&O towpath is in a national one."""
    dirt = {"surface": "dirt"}
    assert v(dirt, WayRoutes(bicycle_networks=frozenset({"rcn"}))) == "natural_surface"
    assert v(dirt, WayRoutes(bicycle_networks=frozenset({"ncn"}))) is None
    assert v(dirt, WayRoutes(bicycle_networks=frozenset({"icn"}))) is None


def test_an_explicit_bicycle_tag_stands_except_for_the_mtb_class():
    assert v({"bicycle": "designated", "surface": "asphalt"}) is None
    assert v({"bicycle": "yes", "surface": "gravel"}) is None
    assert v({"bicycle": "yes", "surface": "dirt"}) == "mtb"
    assert v({"bicycle": "designated", "surface": "dirt", "access": "private"}) == "mtb"
    assert v({"bicycle": "yes", "smoothness": "very_bad"}) == "mtb"
    assert v({"bicycle": "yes"}) is None
    assert v({"bicycle": "yes", "surface": "dirt", "smoothness": "good"}) is None


def test_the_mtb_class_is_read_section_by_section():
    """A paved section of a rated trail stays open; its dirt section is MTB."""
    assert v({"bicycle": "yes", "surface": "asphalt", "mtb:scale": "2"}) is None
    assert v({"bicycle": "yes", "surface": "dirt", "mtb:scale": "0"}) is None
    assert not ta.is_mtb_class({"highway": "path", "surface": "dirt", "mtb:scale": "2"})
    assert ta.is_mtb_class({"highway": "path", "surface": "dirt", "bicycle": "yes"})
    assert ta.is_mtb_class({"highway": "path", "sac_scale": "mountain_hiking", "bicycle": "yes"})


def test_ways_these_rules_never_touch():
    for tags in (
        {"highway": "cycleway", "surface": "dirt"},
        {"highway": "steps", "surface": "dirt"},
        {"highway": "footway", "footway": "sidewalk", "bicycle": "yes", "surface": "dirt"},
        {"highway": "path", "footway": "crossing", "surface": "dirt"},
    ):
        assert ta.verdict(tags) is None


def test_a_way_upstream_already_closes_is_not_marked():
    assert ta.verdict({"highway": "footway", "access": "private"}) is None
    assert ta.verdict({"highway": "path", "bicycle": "no", "surface": "dirt"}) is None
    assert ta.verdict({"highway": "path", "access": "no", "surface": "dirt"}) is None
    assert ta.verdict({"highway": "path", "sac_scale": "mountain_hiking"}) is None
    assert ta.verdict({"highway": "footway", "sac_scale": "hiking"}) == "sac_scale"


def test_upstream_model_reads_the_tables():
    assert ta.upstream_open({"highway": "path"})
    assert not ta.upstream_open({"highway": "footway"})
    assert ta.upstream_open({"highway": "footway", "bicycle": "dismount"})
    assert not ta.upstream_open({"highway": "path", "bicycle": "none"})
    assert ta.upstream_open({"highway": "path", "access": "no", "bicycle": "yes"})


def test_width_parsing():
    assert ta.width_m({"width": "2"}) == 2.0
    assert ta.width_m({"width": "3 m"}) == 3.0
    assert ta.width_m({"width": "6 ft"}) == pytest.approx(1.8288)
    assert ta.width_m({"width": "wide"}) is None
    assert ta.width_m({}) is None


def test_dismount_connectors_keep_when_short_by_chain_length():
    dismount = {"highway": "footway", "bicycle": "dismount"}
    ways = [
        (1, dismount, [10, 11], 100.0),
        (2, dismount, [20, 21], 100.0),
        (3, dismount, [21, 22], 100.0),
        (4, dismount, [30, 31], 150.0),
        (5, {"highway": "footway"}, [40, 41], 900.0),
    ]
    chains = ta.dismount_chains(ways)
    assert set(chains) == {1, 2, 3, 4}
    assert chains[2] == chains[3] == 200.0
    kept, closed = ta.dismount_reasons(chains)
    assert kept == {1}
    assert closed == {2, 3, 4}
