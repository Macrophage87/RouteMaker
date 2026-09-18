"""The reference-data producers, and that what they produce is what the
rebuild loads.

`ReferenceData.load` read `<DATA_ROOT>/reference/{urban-areas,crossings,volume}.json`
and nothing in the repository, compose or docs put anything there: the
crossings fixture was checked in and installed by nothing, and the other two
had no producer. The test runs the script as an operator would and then loads
the result with the production loader.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from rebuild_fixtures import REPO, build_toy_extract

SCRIPT = REPO / "scripts" / "install_reference_data.py"


def geojson(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def test_the_script_installs_every_file_the_loader_requires(tmp_path) -> None:
    from pipeline.extract import read_ways
    from pipeline.run import ReferenceData

    extract = tmp_path / "source.osm.pbf"
    build_toy_extract(extract)

    # An urban area covering the trail and the track but not the road.
    urban = tmp_path / "urban.geojson"
    urban.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {"NAME20": "Washington, DC--VA--MD"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-77.05, 38.905],
                                    [-77.025, 38.905],
                                    [-77.025, 38.93],
                                    [-77.05, 38.93],
                                    [-77.05, 38.905],
                                ]
                            ],
                        },
                    }
                ]
            )
        )
    )
    volume = tmp_path / "volume.geojson"
    volume.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 7, "AADT": "12500"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-77.02, 38.90], [-76.98, 38.90]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 8, "AADT": None},
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    },
                ]
            )
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-root",
            str(tmp_path / "data"),
            "--extract",
            str(extract),
            "--urban-areas",
            str(urban),
            "--volume",
            str(volume),
            "--volume-source",
            "vdot",
            "--volume-year",
            "2024",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    reference = tmp_path / "data" / "reference"
    assert (reference / "crossings.json").read_bytes() == (
        REPO / "fixtures" / "crossings" / "potomac-anacostia.json"
    ).read_bytes()

    ways = read_ways(extract)
    loaded = ReferenceData.load(reference, ways)
    assert loaded.urban_way_ids == {200, 300, 400, 500}, "the road outside the area is rural"
    assert len(loaded.volume_features) == 1, "a count with no AADT is not a count"
    feature = loaded.volume_features[0]
    # `state`, not `vdot`: the field is the precedence tier `conflate` ranks on,
    # and the agency name it used to carry is not in that vocabulary at all.
    assert (feature.aadt, feature.source, feature.year) == (12500, "state", 2024)
    assert feature.feature_id.startswith("vdot-"), "the agency survives in the feature id"
    assert feature.coordinates == [(-77.02, 38.90), (-76.98, 38.90)]
    assert loaded.unmatched_crossings, "the toy extract has none of the real bridges"


def test_without_inputs_the_script_installs_the_fixture_and_names_what_is_missing(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-root", str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert (tmp_path / "reference" / "crossings.json").exists()
    assert "MISSING" in result.stderr and "urban-areas.json" in result.stderr
    assert "volume.json" in result.stderr
    assert Path(tmp_path / "reference" / "volume.json").exists() is False


def test_the_loader_separates_unmatched_crossings_from_unverified_names(tmp_path, caplog) -> None:
    """Two warnings, not one. "Not found in the extract" means the fixture's
    rules are inert on that bridge - the clip moved, or the name changed. "Found, but
    nobody has confirmed the spelling" means the match is believed rather than
    checked, which is the state every row in the shipped fixture is in while
    Overpass is blocked. An operator can act on the first and can only queue the
    second, so folding them into one line hides the distinction the fixture's
    `osm_names_verified` column exists to record.

    `unverified_crossing_names` existed and nothing called it.
    """
    import logging

    from pipeline.extract import Way, read_ways
    from pipeline.run import ReferenceData

    extract = tmp_path / "source.osm.pbf"
    build_toy_extract(extract)

    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "urban-areas.json").write_text("[]")
    (reference / "volume.json").write_text("[]")
    (reference / "crossings.json").write_bytes(
        (REPO / "fixtures" / "crossings" / "potomac-anacostia.json").read_bytes()
    )

    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        ReferenceData.load(reference, read_ways(extract))

    messages = [record.getMessage() for record in caplog.records]
    unmatched = [m for m in messages if "not found in the extract" in m]
    unverified = [m for m in messages if "not yet verified" in m]
    assert len(unmatched) == 1, messages
    assert len(unverified) == 1, messages
    assert unmatched[0] != unverified[0]

    # And the row that shows the two lists answer different questions: one the
    # extract does carry, under a spelling nobody has checked. It is off the
    # unmatched list and still on the unverified one.
    #
    # It used to be Arlington Memorial Bridge, on the reasoning that a row with
    # no `sidepath_only` flag could never be reported unmatched - which was
    # SF-D1 stated as an expectation: the legality half, which every row of the
    # fixture feeds, reported nothing at all, so "not sidepath-only" and "never
    # unmatched" were the same sentence. They are not any more, and a row that
    # genuinely resolves is what the distinction needs.
    (reference / "crossings.json").write_text(
        json.dumps(
            [
                {
                    "name": "Toy Bridge",
                    "osm_names": ["Toy Bridge"],
                    "osm_names_verified": False,
                    "sidepath_only": True,
                    "roadway_bicycle_legal": True,
                }
            ]
        )
    )
    resolvable = [
        Way(
            osm_id=9000,
            tags={"highway": "secondary", "bridge": "yes", "name": "Toy Bridge"},
            node_ids=[],
        )
    ]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        loaded = ReferenceData.load(reference, resolvable)

    messages = [record.getMessage() for record in caplog.records]
    assert not [m for m in messages if "not found in the extract" in m], messages
    assert loaded.unmatched_crossings == ()
    assert loaded.sidepath_bridge_ids == frozenset({9000})
    assert "Toy Bridge" in [m for m in messages if "not yet verified" in m][0]


def test_the_loader_names_crossings_only_the_legality_column_asks_about(tmp_path, caplog) -> None:
    """SF-D1: the warning covers both resolvers, not just the sidepath half.

    `resolve_sidepath_bridge_ids` reported its misses and
    `resolve_bridge_bicycle_legality` reported nothing at all, so the only
    crossings a rebuild ever named were the four `sidepath_only` rows. The other
    fourteen - every row whose whole effect on the graph is `rm:bridge_bicycle`,
    the Theodore Roosevelt Bridge included, whose note says the no-trail variant
    depends entirely on that column - could resolve against nothing and reach no
    log anywhere.

    The reviewer's scenario, run here: an extract carrying only the four
    sidepath bridges. The sidepath half has nothing to report, and the fourteen
    legality rows must still be named.
    """
    import logging

    from pipeline.extract import Way
    from pipeline.run import ReferenceData
    from pipeline.variants import crossing_names

    rows = json.loads((REPO / "fixtures" / "crossings" / "potomac-anacostia.json").read_text())
    sidepath_rows = [row for row in rows if row["sidepath_only"]]
    legality_only = sorted(
        row["name"]
        for row in rows
        if not row["sidepath_only"] and row["roadway_bicycle_legal"] is not None
    )
    assert len(sidepath_rows) == 4 and len(legality_only) == 14, "the fixture's two halves"

    ways = [
        Way(
            osm_id=7000 + index,
            tags={"highway": "secondary", "bridge": "yes", "name": crossing_names(row)[0]},
            node_ids=[],
        )
        for index, row in enumerate(sidepath_rows)
    ]

    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "urban-areas.json").write_text("[]")
    (reference / "volume.json").write_text("[]")
    (reference / "crossings.json").write_bytes(
        (REPO / "fixtures" / "crossings" / "potomac-anacostia.json").read_bytes()
    )

    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        loaded = ReferenceData.load(reference, ways)

    unmatched = [m for m in (r.getMessage() for r in caplog.records) if "not found in" in m]
    assert len(unmatched) == 1, "one warning over the union of both resolvers"
    for name in legality_only:
        assert name in unmatched[0], f"{name} resolved against nothing and was reported nowhere"
    assert "Theodore Roosevelt Bridge" in unmatched[0]
    # And the sidepath half has nothing to add: every one of its rows is here.
    for row in sidepath_rows:
        assert row["name"] not in loaded.unmatched_crossings
    assert sorted(loaded.unmatched_crossings) == legality_only


def line_feature(coordinates: list[list[float]], aadt: str, object_id: int = 1) -> dict:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id, "AADT": aadt},
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def install(tmp_path: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-root", str(tmp_path / "data"), *args],
        capture_output=True,
        text=True,
    )


class TestTwoAgenciesCoveringTheSameRoad:
    """`--volume` is repeatable, and what it writes is a precedence tier.

    Two defects, one symptom. The option was single-valued and the file was
    rewritten per flag, so installing DDOT after VDOT left one agency in it -
    and the region has three count-publishing agencies whose disagreements are
    the whole reason `conflate` has a precedence rule. And the rows carried the
    agency's own name in the `source` field, while
    `conflation.SOURCE_PRECEDENCE` is ("locality", "state", "osm"): every real
    source fell off the end of that tuple to equal lowest precedence, so the
    locality-over-state rule could not fire even once both agencies were in the
    file.
    """

    def test_a_ddot_and_a_vdot_count_on_one_way_resolve_to_the_localitys(self, tmp_path) -> None:
        """End to end: two agency files in, one installed volume.json, loaded by
        the production loader and conflated by the production matcher against a
        way both counts cover. The DDOT count is deliberately the *worse* match
        on geometry - drawn further from the way than VDOT's - so only
        precedence can produce the expected answer."""
        from pipeline.conflation import conflate
        from pipeline.extract import read_ways
        from pipeline.run import ReferenceData

        extract = tmp_path / "source.osm.pbf"
        build_toy_extract(extract)
        # Way 100 in the toy extract: (-77.02, 38.90) to (-76.98, 38.90).
        vdot = tmp_path / "vdot.geojson"
        vdot.write_text(
            json.dumps(geojson([line_feature([[-77.02, 38.90], [-76.98, 38.90]], "24000")]))
        )
        ddot = tmp_path / "ddot.geojson"
        ddot.write_text(
            json.dumps(geojson([line_feature([[-77.02, 38.90004], [-76.98, 38.90004]], "9000", 2)]))
        )

        result = install(
            tmp_path,
            "--volume", str(vdot), "--volume-source", "vdot", "--volume-year", "2024",
            "--volume", str(ddot), "--volume-source", "ddot", "--volume-year", "2024",
        )  # fmt: skip
        assert "MISSING" in result.stderr, "urban-areas is still absent"
        rows = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        assert len(rows) == 2, "the second --volume did not overwrite the first"
        assert {row["source"] for row in rows} == {"state", "locality"}

        (tmp_path / "data" / "reference" / "urban-areas.json").write_text("[]")
        (tmp_path / "data" / "reference" / "crossings.json").write_text("[]")
        reference = ReferenceData.load(tmp_path / "data" / "reference")

        ways = [(w.osm_id, w.coordinates, False) for w in read_ways(extract) if w.osm_id == 100]
        matched = conflate(ways, reference.volume_features).matched
        assert matched[100].aadt == 9000, "the locality's own survey outranks the state's"
        assert matched[100].source == "locality"

    def test_an_unplaced_agency_is_refused_rather_than_ranked_last(self, tmp_path) -> None:
        """Defaulting an unknown agency to "no precedence" is a silent guess at
        which of two agencies wins on a road they both cover, which is the one
        decision this vocabulary exists to make."""
        volume = tmp_path / "counts.geojson"
        volume.write_text(json.dumps(geojson([line_feature([[0, 0], [1, 1]], "100")])))
        result = install(tmp_path, "--volume", str(volume), "--volume-source", "sha-of-narnia")
        assert result.returncode != 0
        assert "unknown --volume-source" in result.stderr
        assert "ddot" in result.stderr and "vdot" in result.stderr

    def test_the_agency_has_no_default_and_is_refused_when_omitted(self, tmp_path) -> None:
        """`--volume-source` used to default to "vdot".

        The agency decides the precedence tier and the precedence tier decides
        which of two agencies wins on a road they both cover, so a default made
        that decision silently - and made it wrong in the common case. A DDOT
        file installed without the flag was filed as state-tier counts and then
        lost the arbitration to VDOT on every District road it shared, which is
        the exact inversion the locality tier exists to prevent. Refused, and
        the refusal names the agencies, the same way an unknown one is.
        """
        volume = tmp_path / "counts.geojson"
        volume.write_text(json.dumps(geojson([line_feature([[0, 0], [1, 1]], "100")])))
        result = install(tmp_path, "--volume", str(volume))
        assert result.returncode == 2
        assert "--volume needs --volume-source" in result.stderr
        assert "ddot" in result.stderr and "vdot" in result.stderr
        assert not (tmp_path / "data" / "reference" / "volume.json").exists()

    def test_the_feature_id_separates_two_files_that_share_an_object_id(self, tmp_path) -> None:
        """F_IRD5: the file stem is in the id, and it is load-bearing.

        One agency publishing one file per county restarts its object ids in
        each of them, and `conflate` keys exclusivity on this id - so two
        counties' counts sharing an id would have one claiming the other's span
        and the other reporting no count at all. Both files here come from the
        same agency and both carry OBJECTID 1, which is exactly the shape that
        collides: the agency prefix cannot separate them and only the stem can.
        Dropping it does not fail quietly - the install refuses on the duplicate
        id backstop - but the backstop is the last line and this is the rule.
        """
        first = tmp_path / "north.geojson"
        first.write_text(json.dumps(geojson([line_feature([[0, 0], [1, 1]], "100", 1)])))
        second = tmp_path / "south.geojson"
        second.write_text(json.dumps(geojson([line_feature([[2, 2], [3, 3]], "200", 1)])))

        result = install(
            tmp_path,
            "--volume", str(first), "--volume", str(second),
            "--volume-source", "montgomery",
        )  # fmt: skip
        assert "two count lines share a feature id" not in result.stderr
        rows = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        ids = [row["id"] for row in rows]
        assert len(set(ids)) == len(ids) == 2, ids
        assert "north" in ids[0] and "south" in ids[1]
        assert [row["aadt"] for row in rows] == [100, 200]

    def test_one_companion_value_covers_every_file(self, tmp_path) -> None:
        """Two files from one agency is the ordinary case and does not have to
        repeat the agency twice; a count that matches neither shape is refused
        rather than silently paired."""
        first = tmp_path / "a.geojson"
        first.write_text(json.dumps(geojson([line_feature([[0, 0], [1, 1]], "100", 1)])))
        second = tmp_path / "b.geojson"
        second.write_text(json.dumps(geojson([line_feature([[2, 2], [3, 3]], "200", 2)])))

        shared = install(
            tmp_path, "--volume", str(first), "--volume", str(second), "--volume-source", "vdot"
        )
        rows = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        assert "MISSING" in shared.stderr
        assert [row["source"] for row in rows] == ["state", "state"]

        mismatched = install(
            tmp_path,
            "--volume", str(first), "--volume", str(second),
            "--volume-source", "vdot", "--volume-source", "ddot", "--volume-source", "osm",
        )  # fmt: skip
        assert mismatched.returncode == 2
        assert "once per file in the same order" in mismatched.stderr


def urban_polygon_to(tmp_path: Path, east: float) -> Path:
    """An urban area covering the toy extract's road from its west end to `east`.

    Way 100 runs from -77.02 to -76.98 at 38.90, so the fraction of it inside is
    (east + 77.02) / 0.04 - which is how these tests put a stated share of one
    way inside a polygon without depending on anything else in the extract.
    """
    path = tmp_path / f"urban-{east}.geojson"
    path.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-77.03, 38.895],
                                    [east, 38.895],
                                    [east, 38.905],
                                    [-77.03, 38.905],
                                    [-77.03, 38.895],
                                ]
                            ],
                        },
                    }
                ]
            )
        )
    )
    return path


class TestTheUrbanLengthFraction:
    """A way is urban when enough of it is inside an urban area, not when it
    touches one.

    Bare intersection graded a Loudoun through road whose end clips Leesburg's
    urban area at the 30 mph urban default along its whole length - the
    lower-stress reading of an ambiguous input, which is the opposite of the
    classifier's rule, on exactly the roads the rural references ride.
    """

    def test_the_threshold_is_a_majority_of_the_ways_length(self) -> None:
        """SF-D3: half, pinned flat, and deliberately not
        `MIN_JURISDICTION_FRACTION`'s 0.10 - which it was pinned equal to, on
        the reasoning that both ask how much of a way has to be inside a polygon
        before the polygon describes it.

        They ask that, and the answers differ, because what a wrong answer costs
        runs in opposite directions. Jurisdiction is inclusive and its output is
        a list of agencies, so over-reporting is the safe direction and a low
        figure is right. Urban is a binary switch onto the *lower*-stress speed
        default - 30 mph assumed instead of 50 - so at a tenth, a Loudoun
        through road with a hundred metres inside Leesburg's urban polygon was
        graded urban end to end and taken out of `is_top_tier`, which is the
        opposite of `stress.py`'s rule of erring toward the higher-stress
        reading of an ambiguous input.

        Pinned against a literal rather than against the other constant, so that
        re-coupling them has to fail here.
        """
        import importlib.util

        from pipeline.run import MIN_JURISDICTION_FRACTION

        spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.MIN_URBAN_FRACTION == 0.5
        assert module.MIN_URBAN_FRACTION != MIN_JURISDICTION_FRACTION

    def test_a_minority_inside_is_rural_and_a_majority_is_urban(self, tmp_path) -> None:
        """The switch, either side of the line, through the real producer over a
        real PBF. Way 100 runs from -77.02 to -76.98, so a polygon reaching
        -77.004 covers two fifths of it and one reaching -76.996 covers three
        fifths.

        Two fifths of a Loudoun through road inside Leesburg's urban area is a
        rural road that ends in a town, and grading it urban assumes 30 mph on
        every mile of it. Three fifths is a town road that runs out into the
        country, and grading it rural assumes 50.
        """
        import importlib.util

        extract = tmp_path / "source.osm.pbf"
        build_toy_extract(extract)

        spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        two_fifths = urban_polygon_to(tmp_path, -77.004)
        three_fifths = urban_polygon_to(tmp_path, -76.996)
        assert 100 not in module.urban_way_ids(extract, two_fifths), "40 percent inside is rural"
        assert 100 in module.urban_way_ids(extract, three_fifths), "60 percent inside is urban"

    def test_a_way_that_clips_an_urban_area_by_its_end_is_not_urban(self, tmp_path) -> None:
        """Through the real producer over a real PBF. Way 100 runs from
        -77.02 to -76.98; the polygon reaches -77.018, so a fiftieth of it is
        inside - the Loudoun-road shape in miniature."""
        import importlib.util

        extract = tmp_path / "source.osm.pbf"
        build_toy_extract(extract)

        spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        clipped = module.urban_way_ids(extract, urban_polygon_to(tmp_path, -77.018))
        assert 100 not in clipped, "a fiftieth of its length inside is not an urban road"
        # Half the way inside, and it is urban - the District street whose last
        # block leaves the boundary is why this is a fraction and not containment.
        assert 100 in module.urban_way_ids(extract, urban_polygon_to(tmp_path, -77.00))


# --- The length ratio's units ----------------------------------------------

L_SHAPED_LAT = 39.0  # the northern half of the coverage box, where the bias is 13 percent
L_SHAPED_DLON = 0.02  # the east-west leg
L_SHAPED_DLAT = L_SHAPED_DLON * math.cos(math.radians(L_SHAPED_LAT))  # the same ground length
L_SHAPED_LON = -77.60


def build_l_shaped_extract(path: Path) -> None:
    """One way that runs east and then turns north, its two legs the same length
    on the ground and therefore *not* the same length in degrees.

    A degree of longitude is 0.777 of a degree of latitude at 39 N, so measuring
    the ratio in degrees weighs the east-west leg 1.29 times the north-south one
    and the answer depends on which way the covered part of the way happens to
    point. A street that turns a corner is the ordinary shape here, not a
    contrived one.
    """
    import osmium

    Path(path).unlink(missing_ok=True)
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (L_SHAPED_LON, L_SHAPED_LAT),
            2: (L_SHAPED_LON + L_SHAPED_DLON, L_SHAPED_LAT),
            3: (L_SHAPED_LON + L_SHAPED_DLON, L_SHAPED_LAT + L_SHAPED_DLAT),
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=100,
                nodes=[1, 2, 3],
                version=1,
                tags={"highway": "secondary", "name": "Corner Road"},
            )
        )
    finally:
        writer.close()


def polygon_file(tmp_path: Path, name: str, west: float, east: float, south: float, north: float):
    path = tmp_path / f"{name}.geojson"
    path.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [west, south],
                                    [east, south],
                                    [east, north],
                                    [west, north],
                                    [west, south],
                                ]
                            ],
                        },
                    }
                ]
            )
        )
    )
    return path


def install_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheLengthRatioIsAGroundRatio:
    """The urban switch may not turn on which way the way points.

    The ratio was measured in degrees, on the reasoning that the local scale
    factor cancels between two lengths of the same way. It cancels only while
    both lengths run in the same direction: a degree of longitude is 0.777 of a
    degree of latitude at 39 N, so on an L-shaped way the two legs are weighed
    differently and a way exactly half inside an urban area reads 0.44 or 0.56
    depending on which of its legs the polygon covers. At the threshold that is
    the difference between assuming 30 mph along the whole way and assuming 50.
    """

    def test_a_corners_two_legs_are_the_same_length_on_the_ground(self, tmp_path) -> None:
        """The premise, so a failure below says which half moved: the two legs
        are equal in metres and 1.29 apart in degrees."""
        from routemaker.geo import Point, haversine

        corner = Point(L_SHAPED_LON + L_SHAPED_DLON, L_SHAPED_LAT)
        west = Point(L_SHAPED_LON, L_SHAPED_LAT)
        north = Point(L_SHAPED_LON + L_SHAPED_DLON, L_SHAPED_LAT + L_SHAPED_DLAT)
        assert haversine(west, corner) == pytest.approx(haversine(corner, north), rel=0.001)
        assert L_SHAPED_DLON / L_SHAPED_DLAT == pytest.approx(1.287, abs=0.005)

    def test_a_majority_of_the_north_south_leg_is_urban(self, tmp_path) -> None:
        """52 percent of the way's length, all of it on the leg that degrees
        under-weigh: 0.46 measured in degrees, so the way was graded rural.
        """
        extract = tmp_path / "corner.osm.pbf"
        build_l_shaped_extract(extract)
        # The whole north-south leg plus 4 percent of the east-west one.
        urban = polygon_file(
            tmp_path,
            "north-leg",
            L_SHAPED_LON + 0.96 * L_SHAPED_DLON,
            L_SHAPED_LON + L_SHAPED_DLON + 0.001,
            L_SHAPED_LAT - 0.001,
            L_SHAPED_LAT + L_SHAPED_DLAT + 0.001,
        )
        assert 100 in install_module().urban_way_ids(extract, urban)

    def test_a_minority_of_the_east_west_leg_is_rural(self, tmp_path) -> None:
        """The mirror image: 48 percent of the way, all of it on the leg degrees
        over-weigh, which read 0.54 and graded the way urban. Both halves are
        needed - a measure that simply ran high or low would pass one of them.
        """
        extract = tmp_path / "corner.osm.pbf"
        build_l_shaped_extract(extract)
        urban = polygon_file(
            tmp_path,
            "east-west-leg",
            L_SHAPED_LON - 0.001,
            L_SHAPED_LON + 0.96 * L_SHAPED_DLON,
            L_SHAPED_LAT - 0.001,
            L_SHAPED_LAT + 0.001,
        )
        assert 100 not in install_module().urban_way_ids(extract, urban)

    def test_overlapping_urban_areas_are_unioned_rather_than_summed(self, tmp_path) -> None:
        """The guard the comment at the union describes, which nothing asserted.

        Two Census urban areas can overlap, and a way lying in the overlap is
        not inside twice. Summing each polygon's intersection separately double
        counts the shared stretch: these two cover 45 percent of the way between
        them and 65 percent if the overlap is counted twice, which is the
        difference between rural and urban at the threshold.
        """
        extract = tmp_path / "source.osm.pbf"
        build_toy_extract(extract)  # way 100 runs from -77.02 to -76.98 at 38.90

        path = tmp_path / "overlapping.geojson"
        path.write_text(
            json.dumps(
                geojson(
                    [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [west, 38.895],
                                        [east, 38.895],
                                        [east, 38.905],
                                        [west, 38.905],
                                        [west, 38.895],
                                    ]
                                ],
                            },
                        }
                        for west, east in ((-77.03, -77.006), (-77.014, -77.002))
                    ]
                )
            )
        )
        assert 100 not in install_module().urban_way_ids(extract, path)
