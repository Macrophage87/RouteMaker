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
import subprocess
import sys
from pathlib import Path

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
    """Two warnings, not one. "Not found in the extract" means the sidepath rule
    is inert on that bridge - the clip moved, or the name changed. "Found, but
    nobody has confirmed the spelling" means the match is believed rather than
    checked, which is the state every row in the shipped fixture is in while
    Overpass is blocked. An operator can act on the first and can only queue the
    second, so folding them into one line hides the distinction the fixture's
    `osm_names_verified` column exists to record.

    `unverified_crossing_names` existed and nothing called it.
    """
    import logging

    from pipeline.extract import read_ways
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
    # Arlington Memorial Bridge is not sidepath-only, so it is never in the
    # unmatched list whatever the extract carries - and it is unverified like
    # every other row. The two lists answer different questions and this is the
    # row that shows it.
    assert "Arlington Memorial Bridge" not in unmatched[0]
    assert "Arlington Memorial Bridge" in unverified[0]


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


class TestTheUrbanLengthFraction:
    """A way is urban when enough of it is inside an urban area, not when it
    touches one.

    Bare intersection graded a Loudoun through road whose end clips Leesburg's
    urban area at the 30 mph urban default along its whole length - the
    lower-stress reading of an ambiguous input, which is the opposite of the
    classifier's rule, on exactly the roads the rural references ride.
    """

    def test_the_threshold_is_the_jurisdiction_fraction(self) -> None:
        """Pinned equal rather than merely similar: both answer the same
        question - how much of a way has to be inside a polygon before the
        polygon describes the way - and two answers to it in one build would be
        two definitions of "mostly outside"."""
        import importlib.util

        from pipeline.run import MIN_JURISDICTION_FRACTION

        spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.MIN_URBAN_FRACTION == MIN_JURISDICTION_FRACTION
        assert module.MIN_URBAN_FRACTION == 0.10

    def test_a_way_that_clips_an_urban_area_by_its_end_is_not_urban(self, tmp_path) -> None:
        """Through the real producer over a real PBF. Way 100 runs from
        -77.02 to -76.98; the polygon reaches -77.018, so a fiftieth of it is
        inside - the Loudoun-road shape in miniature."""
        import importlib.util

        extract = tmp_path / "source.osm.pbf"
        build_toy_extract(extract)

        def polygon(east: float) -> Path:
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

        spec = importlib.util.spec_from_file_location("install_reference_data", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        clipped = module.urban_way_ids(extract, polygon(-77.018))
        assert 100 not in clipped, "a fiftieth of its length inside is not an urban road"
        # Half the way inside, and it is urban - the District street whose last
        # block leaves the boundary is why this is a fraction and not containment.
        assert 100 in module.urban_way_ids(extract, polygon(-77.00))
