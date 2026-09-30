"""No sidewalk riding in DC's Central Business District (routemaker.cbd;
OWNER-DECISIONS 104), against the checked-in boundary and exempt areas."""

from __future__ import annotations

import json

import pytest

from routemaker import cbd

SIDEWALK = {"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}


def line(lon, lat, n=4, dlon=0.0002):
    return [(lon + i * dlon, lat) for i in range(n)]


# Points a sidewalk runs through, and whether it is barred there.
K_STREET = (-77.0330, 38.9025)  # 15th and K NW, downtown
NAVY_YARD = (-77.0040, 38.8760)  # south of the CBD
NATIONAL_MALL = (-77.0250, 38.8895)
CAPITOL_GROUNDS = (-77.0070, 38.8900)
ELLIPSE = (-77.0366, 38.8950)
WASHINGTON_MONUMENT = (-77.0353, 38.8895)


class TestTheFixtures:
    def test_the_boundary_is_ddots_one_polygon(self) -> None:
        data = json.loads(cbd.CBD_FILE.read_text())
        assert [f["properties"]["GIS_ID"] for f in data["features"]] == ["DDOT_CBD_1"]

    def test_the_exempt_areas_are_the_four_named(self) -> None:
        data = json.loads(cbd.EXEMPT_FILE.read_text())
        assert sorted(f["properties"]["name"] for f in data["features"]) == [
            "National Mall",
            "The White House and President's Park",
            "United States Capitol grounds (approximate)",
            "Washington Monument Grounds",
        ]

    @pytest.mark.parametrize(
        "point",
        [NATIONAL_MALL, CAPITOL_GROUNDS, ELLIPSE],  # the Monument grounds lie south of the boundary
    )
    def test_each_exempt_area_lies_inside_the_boundary(self, point) -> None:
        """Otherwise its exemption would be doing nothing."""
        inside, exempt = cbd.areas()
        assert cbd.in_polygons(point, inside)
        assert cbd.in_polygons(point, exempt)


class TestTheRule:
    def test_a_downtown_sidewalk_is_barred(self) -> None:
        assert cbd.barred_sidewalk(SIDEWALK, line(*K_STREET))

    @pytest.mark.parametrize("key", ["footway", "path", "cycleway"])
    def test_a_sidewalk_is_one_whichever_key_maps_it(self, key) -> None:
        tags = {"highway": "path" if key != "cycleway" else "cycleway", key: "sidewalk"}
        assert cbd.barred_sidewalk(tags, line(*K_STREET))

    def test_outside_the_cbd_it_is_not(self) -> None:
        assert not cbd.barred_sidewalk(SIDEWALK, line(*NAVY_YARD))

    @pytest.mark.parametrize(
        "point", [NATIONAL_MALL, CAPITOL_GROUNDS, ELLIPSE, WASHINGTON_MONUMENT]
    )
    def test_on_the_federal_areas_it_is_not(self, point) -> None:
        assert not cbd.barred_sidewalk(SIDEWALK, line(*point))

    @pytest.mark.parametrize(
        "tags",
        [
            # The Pennsylvania Avenue and 15th Street cycle tracks, and any way
            # signed for bicycles.
            {
                "highway": "cycleway",
                "bicycle": "designated",
                "name": "Pennsylvania Avenue cycle track",
            },
            {"highway": "cycleway", "cycleway": "sidewalk", "bicycle": "designated"},
            {"highway": "footway", "footway": "sidewalk", "bicycle": "designated"},
            # A footway that is not a sidewalk, and a road.
            {"highway": "footway", "bicycle": "yes"},
            {"highway": "footway", "footway": "crossing", "bicycle": "yes"},
            {"highway": "secondary", "sidewalk": "both", "name": "K Street Northwest"},
            {"highway": "service", "footway": "sidewalk"},
        ],
    )
    def test_bike_paths_other_footways_and_roads_are_untouched(self, tags) -> None:
        assert not cbd.barred_sidewalk(tags, line(*K_STREET))

    def test_the_way_is_placed_by_the_middle_of_its_length(self) -> None:
        """A sidewalk running out of the CBD is judged where most of it is."""
        _cbd, _exempt = cbd.areas()
        # 1 km east-west along 38.9025: from inside (K St) to far outside.
        mostly_in = [
            K_STREET,
            (K_STREET[0] + 0.001, K_STREET[1]),
            (K_STREET[0] + 0.0015, K_STREET[1]),
        ]
        assert cbd.barred_sidewalk(SIDEWALK, mostly_in)
        mostly_out = [NAVY_YARD, (NAVY_YARD[0] + 0.01, NAVY_YARD[1]), (K_STREET[0], K_STREET[1])]
        assert cbd.midpoint(mostly_out) != mostly_out[-1]
        assert not cbd.in_polygons(cbd.midpoint(mostly_out), _cbd) or cbd.barred_sidewalk(
            SIDEWALK, mostly_out
        )

    def test_midpoint_is_halfway_by_length(self) -> None:
        assert cbd.midpoint([(0.0, 0.0), (1.0, 0.0), (3.0, 0.0)]) == (1.5, 0.0)
        assert cbd.midpoint([(2.0, 1.0)]) == (2.0, 1.0)

    def test_a_hole_is_outside(self) -> None:
        square = [[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]]
        hole = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0), (1.0, 1.0)]
        assert cbd.in_polygons((0.5, 0.5), [square])
        assert not cbd.in_polygons((2.0, 2.0), [[square[0], hole]])
        assert cbd.in_polygons((0.5, 2.0), [[square[0], hole]])
        assert not cbd.in_polygons((5.0, 2.0), [square])

    def test_no_geometry_is_not_barred(self) -> None:
        assert not cbd.barred_sidewalk(SIDEWALK, [])
