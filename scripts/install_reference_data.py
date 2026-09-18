#!/usr/bin/env python3
"""Put the rebuild's reference data where `ReferenceData.load` reads it.

The weekly rebuild refuses to run without three files under
`<DATA_ROOT>/reference/`, because each one stood in for real data in an early
version and each produced a specific wrong map when empty:

    crossings.json     the Potomac and Anacostia crossings fixture, checked in
    urban-areas.json   OSM way ids inside a Census urban area
    volume.json        agency traffic counts, normalised to one AADT definition

Nothing populated the directory. The fixture was checked in and read by
nothing, and the other two had no producer at all. This installs the fixture
and, given the inputs, produces the other two:

    python scripts/install_reference_data.py --data-root /srv/routemaker/data \\
        --extract /srv/routemaker/data/extracts/source.osm.pbf \\
        --urban-areas tl_2024_us_uac20.geojson \\
        --volume vdot-aadt-2024.geojson --volume-source vdot --volume-year 2024 \\
        --volume ddot-aadt-2024.geojson --volume-source ddot --volume-year 2024

`--volume` and its two companions repeat, and the three lists are matched up in
order. The region has three count-publishing agencies and the conflation step
exists precisely to arbitrate between them on a road they both cover, so a
single-valued option could not express the input that makes the arbitration
mean anything: installing DDOT after VDOT overwrote the file and left one
agency, and the precedence rule had nothing to choose between.

Run with only --data-root it installs the crossings and reports which of the
other two are still missing, exiting non-zero while any is. See
docs/DEVELOPMENT.md, "Reference data", for where each input comes from.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CROSSINGS_FIXTURE = REPO / "fixtures" / "crossings" / "potomac-anacostia.json"
REQUIRED = ("crossings.json", "urban-areas.json", "volume.json")

# Agency to precedence tier. `conflation.SOURCE_PRECEDENCE` is
# ("locality", "state", "osm") - tiers, not agencies - and this script wrote the
# agency's own name into the `source` field the ranking reads. Every real source
# therefore fell off the end of the tuple to the lowest precedence, where
# `conflate` ranks them all equally and the locality-over-state rule could never
# fire: measured on one way covered by both a DDOT and a VDOT count, the two
# came out two tiers apart in the wrong direction and which one won was decided
# by overlap and distance instead.
#
# The tier is resolved here, at install time, rather than in `conflate`, for two
# reasons. This is the only place that knows which agency a file came from - by
# the time `conflate` sees a row there is no agency left to map - and it is the
# place an operator adding a fourth agency is already editing, so an unknown
# agency can be refused with a message naming the ones it knows instead of
# resolving to "no precedence" three stages later.
#
# The agency name is not lost: it stays in each row's feature id, which is what
# a reviewer reads when two agencies disagree about the same road.
SOURCE_TIERS = {
    # A locality surveys its own streets more densely than the state does, which
    # is the whole reason the precedence rule prefers it.
    "ddot": "locality",
    "montgomery": "locality",
    "arlington": "locality",
    "alexandria": "locality",
    "fairfax": "locality",
    "loudoun": "locality",
    "prince-georges": "locality",
    # State DOTs.
    "vdot": "state",
    "mdot-sha": "state",
    "mdsha": "state",
    # Derived from OSM's own tagging rather than surveyed by anyone.
    "osm": "osm",
}

# A way is graded urban only if a majority of its length lies inside a Census
# urban area.
#
# Deliberately *not* `pipeline.run`'s `MIN_JURISDICTION_FRACTION`, which it was
# pinned equal to. The two thresholds look like one question - how much of a way
# has to be inside a polygon before the polygon describes the way - and they are
# not, because what each answer costs when it is wrong runs in opposite
# directions.
#
# `MIN_JURISDICTION_FRACTION` is inclusive and its output is a list: a way ten
# percent inside Arlington names Arlington *as well as* whoever else it touches,
# and the organizer reading the jurisdiction report hears about one more agency
# than the ride strictly needs a permit from. Over-reporting is the safe
# direction there, so a low figure is the right one.
#
# This one is a binary switch, and it switches the default speed table: urban
# assumes 30 mph where nothing is posted, rural assumes 50. Ten percent
# therefore meant a Loudoun through road with a hundred metres inside
# Leesburg's urban polygon was graded urban end to end - the *lower*-stress
# reading of an ambiguous input on every mile of it, which is precisely what
# `stress.py`'s defaults exist to refuse ("each erring toward the higher-stress
# reading"), and it takes such a road out of `is_top_tier`, which is what
# Beginner's zero-top-tier-distance invariant and the road-exposure report key
# on. A majority is the figure that makes the switch describe the way rather
# than its end: below half, the rural reading stands, which is the conservative
# one.
#
# The error in the other direction is real too and is why this is a fraction
# rather than containment: a District street whose last block leaves the
# boundary is an urban street, and containment would grade it rural. Half is
# where the two trade off.
MIN_URBAN_FRACTION = 0.5


def install_crossings(reference: Path) -> Path:
    destination = reference / "crossings.json"
    json.loads(CROSSINGS_FIXTURE.read_text())  # refuse to install a broken fixture
    shutil.copyfile(CROSSINGS_FIXTURE, destination)
    return destination


def _geometries(geojson: Path):
    from shapely.geometry import shape

    document = json.loads(geojson.read_text())
    features = document["features"] if document.get("type") == "FeatureCollection" else [document]
    for feature in features:
        geometry = feature.get("geometry") if "geometry" in feature else feature
        if geometry:
            yield shape(geometry), feature.get("properties") or {}


def urban_way_ids(
    extract: Path, urban_areas: Path, min_fraction: float = MIN_URBAN_FRACTION
) -> list[int]:
    """Ways with at least `min_fraction` of their length inside an urban area.

    Not containment, so a street that leaves the urban boundary is still graded
    against urban speeds - the alternative grades the last block of a District
    street as rural. And not bare intersection either, which is what this was:
    a way was urban if it touched a polygon anywhere, so a Loudoun through road
    whose end clips Leesburg's urban area was graded at the 30 mph urban default
    along its whole length. Both errors are real; a majority is where they trade
    off, and the asymmetry that puts it there rather than at
    `MIN_JURISDICTION_FRACTION`'s figure is written at the constant.

    Length is measured with the two axes weighed against each other by
    cos(latitude), which is the cheapest thing that makes the ratio a ratio of
    ground lengths. Raw degrees do not cancel the way the earlier comment
    claimed they do: they cancel only while the covered stretch and the whole
    way run in the same direction, because a degree of longitude is 0.78 of a
    degree of latitude at 39 N and the two axes therefore weigh differently. On
    an L-shaped way with one leg east-west and one north-south - a street that
    turns a corner, which is most of them - that bias runs to 13 percent either
    way at the threshold: a way exactly half inside read 0.46 when the inside
    half was the north-south leg and 0.54 when it was the east-west one, so
    which way the covered part happened to point decided whether the road was
    graded at the urban 30 mph default or the rural 50.

    The latitude axis is divided by the cosine rather than the longitude axis
    multiplied by it, which is the same ratio in different units - degrees of
    longitude at this way's latitude instead of metres - and leaves an
    east-west way's coordinates untouched rather than rounding every one of
    them. The scaling is affine, so it commutes with the intersection and can be
    applied to the result rather than to every polygon.
    """
    from shapely.affinity import scale
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    from pipeline.extract import read_ways

    polygons = [geometry for geometry, _ in _geometries(urban_areas)]
    if not polygons:
        raise SystemExit(f"{urban_areas} holds no polygons")
    index = STRtree(polygons)
    ids = []
    for way in read_ways(extract):
        if len(way.coordinates) < 2:
            continue
        line = LineString(way.coordinates)
        nearby = [polygons[i] for i in index.query(line)]
        if not nearby:
            continue
        # A way spans a few kilometres, so one cosine for the whole of it is
        # exact to far better than the threshold's one significant figure.
        cosine = math.cos(math.radians(line.centroid.y))

        def metric_length(geometry, cosine=cosine) -> float:
            return scale(geometry, xfact=1.0, yfact=1.0 / cosine, origin=(0, 0)).length

        # Unioned before the intersection is measured: two adjacent urban areas
        # each covering a third of a way describe a way two thirds urban, and
        # summing the pieces separately would double-count any overlap between
        # them.
        inside = metric_length(line.intersection(unary_union(nearby)))
        total = metric_length(line)
        if total > 0 and inside / total >= min_fraction:
            ids.append(way.osm_id)
    return sorted(ids)


def volume_rows(volume: Path, source: str, year: int | None, aadt_property: str) -> list[dict]:
    """Agency count lines in the shape `conflation.AgencyFeature` is built from.

    Bidirectional AADT is the one definition; an agency publishing directional
    counts has to be summed before it reaches here, which is why the property
    name is an argument rather than guessed.

    `source` is the agency; what lands in each row's `source` field is that
    agency's precedence tier, which is the vocabulary `conflation.conflate`
    ranks on. The agency itself survives in the feature id, so a reviewer
    looking at two rows that disagree about one road can still see which agency
    published which count.
    """
    tier = source_tier(source)
    rows = []
    for number, (geometry, properties) in enumerate(_geometries(volume)):
        value = properties.get(aadt_property)
        if value in (None, ""):
            continue
        lines = (
            [geometry]
            if geometry.geom_type == "LineString"
            else list(getattr(geometry, "geoms", []))
        )
        for part, line in enumerate(lines):
            if line.geom_type != "LineString":
                continue
            rows.append(
                {
                    # Agency, then the file it came from, then the agency's own
                    # object id. The file is in there because `--volume`
                    # repeats: an agency that publishes one file per county
                    # restarts its object ids in each of them, and `conflate`
                    # keys exclusivity on this id, so two counties' counts
                    # sharing an id would have one claiming the other's span.
                    "id": f"{source}-{volume.stem}-{properties.get('OBJECTID', number)}-{part}",
                    "coordinates": [[x, y] for x, y in line.coords],
                    "aadt": int(float(value)),
                    "source": tier,
                    "agency": source,
                    "year": year,
                }
            )
    return rows


def source_tier(source: str) -> str:
    """The precedence tier an agency's counts rank at.

    Refused rather than defaulted. A tier chosen for an agency nobody has placed
    is a silent guess at which of two agencies should win on a road they both
    cover, which is the one decision this vocabulary exists to make.
    """
    try:
        return SOURCE_TIERS[source.strip().casefold()]
    except KeyError:
        known = ", ".join(sorted(SOURCE_TIERS))
        raise SystemExit(
            f"unknown --volume-source {source!r}: add it to SOURCE_TIERS with the precedence "
            f"tier its counts should rank at. Known agencies: {known}"
        ) from None


def _per_volume(parser, flag: str, values: list, volumes: list, default):
    """One value of `flag` per `--volume`, or one value shared by all of them.

    Repeating every companion flag for a single-agency install would be noise,
    and silently pairing three files with one agency name would be worse than
    noise, so the two readable shapes are allowed and anything else is refused
    with the counts named.
    """
    if not values:
        return [default] * len(volumes)
    if len(values) == 1:
        return values * len(volumes)
    if len(values) != len(volumes):
        parser.error(
            f"{flag} given {len(values)} times for {len(volumes)} --volume files; "
            f"give it once, or once per file in the same order"
        )
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-root", type=Path, default=Path(os.environ.get("DATA_ROOT", REPO / "data"))
    )
    parser.add_argument("--extract", type=Path, help="the source OSM extract, for --urban-areas")
    parser.add_argument("--urban-areas", type=Path, help="Census urban-area polygons, GeoJSON")
    # Repeatable, and matched up in order with its two companions. The region
    # has three count-publishing agencies and the conflation step exists to
    # arbitrate between them on a road they all cover; a single-valued option
    # wrote the file once per flag, so installing DDOT after VDOT left one
    # agency in it and the precedence rule had nothing to choose between.
    parser.add_argument(
        "--volume", type=Path, action="append", default=[], help="agency count lines, GeoJSON"
    )
    parser.add_argument(
        "--volume-source",
        action="append",
        default=[],
        help=(
            "the publishing agency, required with --volume, once or one per file "
            f"({', '.join(sorted(SOURCE_TIERS))})"
        ),
    )
    parser.add_argument("--volume-year", type=int, action="append", default=[])
    parser.add_argument("--aadt-property", action="append", default=[])
    args = parser.parse_args(argv)

    reference = args.data_root / "reference"
    reference.mkdir(parents=True, exist_ok=True)

    print(f"installed {install_crossings(reference)}")

    if args.urban_areas:
        if not args.extract:
            parser.error("--urban-areas needs --extract")
        ids = urban_way_ids(args.extract, args.urban_areas)
        (reference / "urban-areas.json").write_text(json.dumps(ids))
        print(f"wrote {reference / 'urban-areas.json'}: {len(ids)} urban ways")

    if args.volume:
        # Refused rather than defaulted, for the reason `source_tier` refuses an
        # agency it does not know: the agency name decides the precedence tier,
        # and the precedence tier decides which of two agencies wins on a road
        # they both cover. A default made that decision silently and made it
        # wrong in the common case - the default was `vdot`, so a DDOT file
        # installed without the flag was filed as state-tier counts and lost the
        # arbitration to VDOT on every District road, which is the exact
        # inversion the locality tier exists to prevent.
        if not args.volume_source:
            parser.error(
                "--volume needs --volume-source: the agency decides the precedence tier, "
                f"and there is no safe default. Known agencies: {', '.join(sorted(SOURCE_TIERS))}"
            )
        sources = _per_volume(parser, "--volume-source", args.volume_source, args.volume, None)
        years = _per_volume(parser, "--volume-year", args.volume_year, args.volume, None)
        properties = _per_volume(parser, "--aadt-property", args.aadt_property, args.volume, "AADT")
        rows: list[dict] = []
        for path, source, year, aadt_property in zip(
            args.volume, sources, years, properties, strict=True
        ):
            produced = volume_rows(path, source, year, aadt_property)
            print(f"  {path}: {len(produced)} count lines from {source} ({source_tier(source)})")
            rows.extend(produced)
        if len({row["id"] for row in rows}) != len(rows):
            # The id is built to be unique, so this is a backstop rather than a
            # rule: it fires if the same file is given twice, which produces two
            # identical sets of counts and doubles nothing but the arbitration.
            parser.error(
                "two count lines share a feature id; `conflate` keys exclusivity on it, so "
                "one count would claim another's span. Was a --volume file given twice?"
            )
        (reference / "volume.json").write_text(json.dumps(rows))
        print(f"wrote {reference / 'volume.json'}: {len(rows)} count lines")

    missing = [name for name in REQUIRED if not (reference / name).exists()]
    for name in missing:
        print(f"MISSING {reference / name}; the rebuild will refuse to run", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
