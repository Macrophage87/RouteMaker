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
            --aadt-property ADT \\
        --volume ddot-aadt-2024.geojson --volume-source ddot --volume-year 2024 \\
            --aadt-property AADT

(VDOT's export names its count `ADT`; without `--aadt-property ADT` it installs
0 Virginia count lines and still exits 0. docs/OPERATIONS.md, step 6.)

`--volume` and its companions repeat, and the lists are matched up in
order. The region has three count-publishing agencies and the conflation step
exists precisely to arbitrate between them on a road they both cover, so a
single-valued option could not express the input that makes the arbitration
mean anything: installing DDOT after VDOT overwrote the file and left one
agency, and the precedence rule had nothing to choose between.

Census county polygons go to `counties.geojson`, optional, read only by the cloud
import's stress change report (`core.stress_changes`: totals by county), and
filtered to the counties the coverage box reaches:

    --counties tl_2024_us_county.geojson

Three agency street layers go to `roadway.json`, optional, read by the rebuild's
volume-conflation stage (OWNER-DECISIONS 151, 159; PLAN.md item 183):

    --roadway-block dc-roadway-block.geojson          DDOT, CC BY 4.0
    --baltimore-centerline baltimore-street-centerline.geojson   Open Baltimore
    --alexandria-streets alexandria-transport-streets.geojson    City of Alexandria, CC0

Each is the layer exactly as `scripts/fetch_agency_layer.py` stored it; the
posted speed, lanes by direction, one-way, bike facility, parking and count are
parsed by `routemaker.agency_roads`.

DDOT's Pavement Condition Index goes to `pavement.json`, optional (DC-PCI):

    --dc-pci dc-pavement-pci-fy25.geojson   DDOT / DC GIS, FY-25 layer

parsed by `routemaker.pavement`; `--dc-pci-fiscal-year` names the layer's year
(default 2025) for the blocks whose survey date is empty.

The Scenic layer's agency lines go to `scenic.json`, optional, read by the
rebuild's scenic stage (`pipeline.scenic_layer`; v0.8.0), never by the classifier:

    --rustic-roads moco-rustic-roads.geojson    Montgomery County Planning
    --scenic-byways md-scenic-byways.geojson    MDOT SHA (MD iMAP)

each as `scripts/fetch_agency_layer.py` stored it; `--byway-name-field` names the
byway layer's name field, and `--rustic-name-field` the rustic roads' road-name field,
where it is not one `routemaker.scenic` looks for (a layer with none is refused).

The agencies' traffic signal lists go to `signals.json`, optional, read by the
rebuild's tag stage (`pipeline.agency_signals`; v0.10.0) to mark the junctions at a
signal OSM does not map:

    --dc-signals dc-traffic-signals.geojson          DDOT / DC GIS, Traffic Signals
    --md-signals md-traffic-signals.geojson          MDOT SHA, Traffic Signals
    --va-signals va-traffic-signals.geojson          VDOT, HMMS Traffic Signals (2023)
    --arlington-signals arlington-intersections.geojson
                                                     Arlington, Intersection Points
    --alexandria-signals alexandria-signals.geojson  Alexandria, Smart Mobility layer 9
    --alexandria-hawks alexandria-hawks.geojson      Alexandria, layer 0, signal_type HAWK

each as `scripts/fetch_agency_layer.py` stored it, all in one file written whole: a
rerun with one flag replaces the others' rows, so give them all each time. A record
that is not a running signal is left out, and the count of each reason is printed.
With --md-signals it also writes `flashing-signals.json`: MDOT SHA's junction beacons
(flashing lights the map may have as signals), loaded into the api with
`manage.py load_flashing_signals` (docs/OPERATIONS.md, "Flashing beacons").

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

from routemaker import mdot_aadt  # noqa: E402 - needs the path above

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
# The agency name is not lost: each row carries it in an `agency` field of its
# own, and in its feature id. The field is the one that travels - through
# `AgencyFeature`, `Match` and `StressResult` into the segment table's
# `volume_source` column - because two agencies at one tier are otherwise
# indistinguishable in the published derivative.
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
    # Derived from OSM's own tagging rather than surveyed by anyone.
    "osm": "osm",
}

# Other spellings of an agency in SOURCE_TIERS, accepted on the command line and
# written as the one name. Not a second key in SOURCE_TIERS: that ranked both
# spellings alike and then wrote whichever one was typed into the `agency`
# field, so one agency's counts reached the segment table's `volume_source` as
# two different strings and a query for the segments it influenced found half.
AGENCY_ALIASES = {"mdsha": "mdot-sha"}


def canonical_agency(source: str) -> str:
    """The one name an agency is recorded under, whatever the flag said.

    Casefolded and stripped as the tier lookup always was - the tier already
    came from `VDOT` and `vdot` alike while the `agency` field kept the raw
    argument, so the two spellings ranked the same and published as two
    agencies - and then put through the aliases. An agency this does not know
    is returned in the same normal form and left for `source_tier` to refuse.
    """
    folded = source.strip().casefold()
    return AGENCY_ALIASES.get(folded, folded)


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


# A piece's boundary is at most this many vertices, so measuring a way against
# the pieces near it costs a few hundred vertices rather than the whole urban
# area's boundary.
URBAN_PIECE_VERTICES = 256


def _small_pieces(area, max_vertices: int = URBAN_PIECE_VERTICES) -> list:
    """`area` split into quadrants, recursively, until no piece's boundary has
    more than `max_vertices` vertices. The pieces tile `area` exactly: they
    share edges and no area."""
    import shapely

    pieces = []
    pending = [part for part in getattr(area, "geoms", [area]) if part.area > 0]
    while pending:
        piece = pending.pop()
        if shapely.get_num_coordinates(piece) <= max_vertices:
            pieces.append(piece)
            continue
        west, south, east, north = piece.bounds
        middle_x, middle_y = (west + east) / 2, (south + north) / 2
        for quadrant in (
            (west, south, middle_x, middle_y),
            (middle_x, south, east, middle_y),
            (west, middle_y, middle_x, north),
            (middle_x, middle_y, east, north),
        ):
            clipped = shapely.clip_by_rect(piece, *quadrant)
            for part in getattr(clipped, "geoms", [clipped]):
                if part.geom_type == "Polygon" and part.area > 0:
                    pending.append(part)
    return pieces


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
    # Cut once, measured per way. The Washington--Arlington urban area is one
    # polygon with a boundary hundreds of thousands of vertices long, nearly
    # every way in the region touches it, and an intersection costs the whole
    # boundary: intersecting each way with the polygons themselves took hours on
    # the real extract. So the union is taken once and split into small pieces,
    # and a way is measured against the union of only the pieces it touches -
    # re-unioned so that a way running along a cut is not counted twice. The
    # union and the split change no area, so the fraction is the one the whole
    # polygons give (tests/test_reference_data_install.py).
    pieces = _small_pieces(unary_union(polygons))
    index = STRtree(pieces)
    ids = []
    for way in read_ways(extract):
        if len(way.coordinates) < 2:
            continue
        line = LineString(way.coordinates)
        nearby = [pieces[i] for i in index.query(line, predicate="intersects")]
        if not nearby:
            continue
        if len(nearby) == 1 and nearby[0].contains(line):
            ids.append(way.osm_id)
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


# src/config/settings.py COVERAGE_BBOX (west, south, east, north), which this script
# cannot import without a configured Django; tests/test_reference_data_install.py holds
# the two the same.
COVERAGE_BBOX = (-78.05, 38.2, -76.02, 39.72)


def install_counties(counties: Path, target: Path) -> int:
    """The counties in `counties` that reach the coverage box, written to `target`
    as a FeatureCollection with the properties the report names them by."""
    from shapely.geometry import box, mapping

    area = box(*COVERAGE_BBOX)
    features = [
        {
            "type": "Feature",
            "properties": {
                key: properties[key]
                for key in ("NAME", "NAMELSAD", "STATEFP", "STUSPS", "GEOID")
                if key in properties
            },
            "geometry": mapping(geometry),
        }
        for geometry, properties in _geometries(counties)
        if geometry.intersects(area)
    ]
    if not features:
        raise SystemExit(f"{counties} holds no county inside the coverage box")
    target.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


def volume_rows(volume: Path, source: str, year: int | None, aadt_property: str) -> list[dict]:
    """Agency count lines in the shape `conflation.AgencyFeature` is built from.

    Bidirectional AADT is the one definition; an agency publishing directional
    counts has to be summed before it reaches here, which is why the property
    name is an argument rather than guessed.

    `source` is the agency; what lands in each row's `source` field is that
    agency's precedence tier, which is the vocabulary `conflation.conflate`
    ranks on. The agency itself is written to a field of its own, and to the
    feature id, so a reviewer looking at two rows that disagree about one road
    can see which agency published which count.

    The separate `agency` field is what reaches the published segment table,
    and it is not decoration on the feature id: VDOT and MDOT SHA both rank at
    "state", so while only the tier travelled past `ReferenceData.load` the
    derivative recorded one indistinguishable source for both - and PLAN:31-34
    asks it to be able to name the segments a conditionally licensed Maryland
    layer influenced.
    """
    tier = source_tier(source)
    agency = canonical_agency(source)
    features = list(_geometries(volume))
    # MDOT SHA's layer (FOLLOWUP-MDOT-AADT, OWNER-DECISIONS 429; `routemaker.mdot_aadt`):
    # a row the agency flags as misplaced (`LOC_ERROR`) is not installed, and the
    # year `AADT` is for is read from the layer's dated fields where no
    # `--volume-year` was given, so an operator cannot file 2024's counts as 2023's.
    maryland = agency == mdot_aadt.AGENCY
    if maryland and year is None:
        year = mdot_aadt.current_year({key for _, properties in features for key in properties})
    skipped = 0
    rows = []
    for number, (geometry, properties) in enumerate(features):
        value = properties.get(aadt_property)
        if value in (None, ""):
            continue
        if maryland and not mdot_aadt.usable(properties):
            skipped += 1
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
                    "id": f"{agency}-{volume.stem}-{properties.get('OBJECTID', number)}-{part}",
                    "coordinates": [[x, y] for x, y, *_ in line.coords],
                    "aadt": int(float(value)),
                    "source": tier,
                    "agency": agency,
                    "year": year,
                }
            )
    if skipped:
        print(f"  {volume}: {skipped} rows not installed (no count above zero, or LOC_ERROR set)")
    return rows


def roadway_rows(
    roadway_block: Path | None, baltimore: Path | None, alexandria: Path | None = None
) -> list[dict]:
    """Agency street blocks in the shape `ReferenceData.load_road_blocks` reads.

    Streamed one feature at a time: the Baltimore centerline is 152 MB of
    attribute columns that are mostly empty. A block carrying nothing the
    classifier uses (a Baltimore line with no speed and no one-way) is left out
    rather than stored to match nothing.
    """
    from routemaker import agency_roads

    rows: list[dict] = []

    def lines(geometry):
        if not geometry:
            return
        if geometry["type"] == "LineString":
            yield geometry["coordinates"]
        elif geometry["type"] == "MultiLineString":
            yield from geometry["coordinates"]

    layers = (
        (roadway_block, "dc", lambda props: agency_roads.parse_dc_roadway_block(props)),
        (baltimore, "baltimore", agency_roads.parse_baltimore_centerline),
        (alexandria, "alexandria", agency_roads.parse_alexandria_transport_streets),
    )
    for path, prefix, parse in layers:
        if path is None:
            continue
        # The internal-comparison layer (Arlington's Bike Comfort Index;
        # OWNER-DECISIONS 155) is never a rebuild input.
        agency_roads.refuse_internal_only(path)
        kept = 0
        for number, feature in enumerate(agency_roads.iter_features(path)):
            properties = feature.get("properties") or {}
            facts = parse(properties)
            if facts is None:
                continue
            useful = facts.speed_mph or facts.lanes or facts.way or facts.bike or facts.aadt
            if not useful and facts.parking_lanes is None:
                continue
            object_id = properties.get("OBJECTID", feature.get("id", number))
            for part, line in enumerate(lines(feature.get("geometry"))):
                if len(line) < 2:
                    continue
                rows.append(
                    {
                        "id": f"{prefix}-{object_id}-{part}",
                        "coordinates": [[round(x, 7), round(y, 7)] for x, y, *_ in line],
                        "facts": facts.to_json(),
                    }
                )
                kept += 1
        print(f"  {path}: {kept} street blocks ({prefix})")
    return rows


def source_tier(source: str) -> str:
    """The precedence tier an agency's counts rank at.

    Refused rather than defaulted. A tier chosen for an agency nobody has placed
    is a silent guess at which of two agencies should win on a road they both
    cover, which is the one decision this vocabulary exists to make.
    """
    try:
        return SOURCE_TIERS[canonical_agency(source)]
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
    parser.add_argument(
        "--counties", type=Path, help="Census county polygons (TIGER), GeoJSON, for reports"
    )
    parser.add_argument("--aadt-property", action="append", default=[])
    parser.add_argument(
        "--roadway-block", type=Path, help="DC DCGIS Roadway Block, GeoJSON as fetched"
    )
    parser.add_argument(
        "--baltimore-centerline", type=Path, help="Baltimore street centerline, GeoJSON as fetched"
    )
    parser.add_argument(
        "--alexandria-streets",
        type=Path,
        help="City of Alexandria Transport Streets (CC0), GeoJSON as fetched",
    )
    parser.add_argument(
        "--dc-pci", type=Path, help="DDOT Pavement Condition Index layer, GeoJSON as fetched"
    )
    parser.add_argument("--dc-pci-fiscal-year", type=int, default=None)
    parser.add_argument(
        "--rustic-roads", type=Path, help="Montgomery County Rustic Roads, GeoJSON as fetched"
    )
    parser.add_argument(
        "--scenic-byways", type=Path, help="MDOT SHA Scenic Byways (MD iMAP), GeoJSON as fetched"
    )
    parser.add_argument(
        "--dc-signals", type=Path, help="DDOT Traffic Signals (DC GIS), GeoJSON as fetched"
    )
    parser.add_argument("--md-signals", type=Path, help="MDOT SHA Traffic Signals, GeoJSON")
    parser.add_argument(
        "--va-signals", type=Path, help="VDOT HMMS Traffic Signals (2023 Snapshot), GeoJSON"
    )
    parser.add_argument(
        "--arlington-signals", type=Path, help="Arlington Intersection Points, GeoJSON"
    )
    parser.add_argument(
        "--alexandria-signals", type=Path, help="Alexandria signalised intersections, GeoJSON"
    )
    parser.add_argument("--alexandria-hawks", type=Path, help="Alexandria HAWKs, GeoJSON")
    parser.add_argument(
        "--bikeshare-trips",
        type=Path,
        help="the dock-to-dock trip counts (scripts/build_bikeshare_trips.py), for the "
        "popular bike corridors; never published",
    )
    parser.add_argument("--byway-name-field", default=None)
    parser.add_argument("--rustic-name-field", default=None)
    args = parser.parse_args(argv)
    if args.dc_pci:
        # Refused before anything is written while the licence is unconfirmed (DC-PCI).
        from routemaker import pavement

        if not pavement.LICENCE_CONFIRMED:
            parser.error(f"--dc-pci refused: {pavement.LICENCE_PENDING}")

    # The internal-comparison layer (Arlington's Bike Comfort Index;
    # OWNER-DECISIONS 155) is never a rebuild input. Refused before anything is
    # written (review r2: the crossings fixture was installed first, so a refused
    # run still changed the data root).
    from routemaker.agency_roads import InternalOnlySource, refuse_internal_only

    inputs = (
        args.extract,
        args.urban_areas,
        args.roadway_block,
        args.baltimore_centerline,
        args.alexandria_streets,
        args.dc_pci,
        args.rustic_roads,
        args.scenic_byways,
        args.dc_signals,
        args.md_signals,
        args.va_signals,
        args.arlington_signals,
        args.alexandria_signals,
        args.alexandria_hawks,
    )
    for path in (*inputs, *args.volume):
        if path is None:
            continue
        try:
            refuse_internal_only(path)
        except InternalOnlySource as refused:
            parser.error(str(refused))

    reference = args.data_root / "reference"
    reference.mkdir(parents=True, exist_ok=True)

    print(f"installed {install_crossings(reference)}")

    if args.counties:
        target = reference / "counties.geojson"
        kept = install_counties(args.counties, target)
        print(f"wrote {target}: {kept} counties")

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

    if args.roadway_block or args.baltimore_centerline or args.alexandria_streets:
        try:
            blocks = roadway_rows(
                args.roadway_block, args.baltimore_centerline, args.alexandria_streets
            )
        except InternalOnlySource as refused:
            parser.error(str(refused))
        if len({row["id"] for row in blocks}) != len(blocks):
            parser.error("two street blocks share an id")
        (reference / "roadway.json").write_text(json.dumps(blocks, separators=(",", ":")))
        print(f"wrote {reference / 'roadway.json'}: {len(blocks)} street blocks")

    if args.dc_pci:
        from routemaker import pavement

        year = args.dc_pci_fiscal_year or pavement.FISCAL_YEAR
        blocks = pavement.parse_layer(json.loads(args.dc_pci.read_text()), year)
        if len({block.feature_id for block in blocks}) != len(blocks):
            parser.error("two pavement blocks share an id")
        rows = [block.to_json() for block in blocks]
        (reference / "pavement.json").write_text(json.dumps(rows, separators=(",", ":")))
        print(f"wrote {reference / 'pavement.json'}: {len(rows)} pavement blocks (FY{year})")

    if args.rustic_roads or args.scenic_byways:
        # Both sources in one file, written whole: a rerun with one flag replaces the
        # other's rows, so give both each time (docs/OPERATIONS.md, the Scenic layer).
        from routemaker import scenic

        rows = []
        try:
            for path, parse in (
                (args.rustic_roads, lambda doc: scenic.rustic_rows(doc, args.rustic_name_field)),
                (args.scenic_byways, lambda doc: scenic.byway_rows(doc, args.byway_name_field)),
            ):
                if path is None:
                    continue
                produced, dropped = parse(json.loads(path.read_text()))
                print(f"  {path}: {len(produced)} scenic lines, {dropped} records left out")
                rows.extend(produced)
        except scenic.LayerUnreadable as unreadable:
            parser.error(str(unreadable))
        if len({row["id"] for row in rows}) != len(rows):
            parser.error("two scenic lines share an id")
        (reference / "scenic.json").write_text(json.dumps(rows, separators=(",", ":")))
        print(f"wrote {reference / 'scenic.json'}: {len(rows)} scenic lines")

    signal_inputs = (
        (args.dc_signals, "ddot_rows", {}),
        (args.md_signals, "mdot_sha_rows", {}),
        (args.va_signals, "vdot_rows", {}),
        (args.arlington_signals, "arlington_rows", {}),
        (args.alexandria_signals, "alexandria_rows", {}),
        (args.alexandria_hawks, "alexandria_rows", {"kind": "hawk"}),
    )
    if any(path for path, _parse, _options in signal_inputs):
        from pipeline import agency_signals

        rows = []
        for path, parse, options in signal_inputs:
            if path is None:
                continue
            produced, dropped = getattr(agency_signals, parse)(
                json.loads(path.read_text()), **options
            )
            for reason, count in sorted(dropped.items()):
                print(f"  {path}: {count} records left out ({reason})")
            print(f"  {path}: {len(produced)} signals")
            rows.extend(produced)
        if len({row["id"] for row in rows}) != len(rows):
            parser.error("two signals share an id; was a signal file given twice?")
        hawks = sum(1 for row in rows if row["kind"] == "hawk")
        target = reference / agency_signals.FILE_NAME
        target.write_text(json.dumps(rows, separators=(",", ":")))
        print(f"wrote {target}: {len(rows)} signals ({hawks} HAWKs)")
        if args.md_signals is not None:
            # MDOT SHA's junction beacons, for `manage.py load_flashing_signals`.
            beacons = agency_signals.mdot_sha_beacons(json.loads(args.md_signals.read_text()), rows)
            for reason, count in sorted(beacons.pop("dropped").items()):
                print(f"  {args.md_signals}: {count} beacons left out ({reason})")
            target = reference / agency_signals.BEACONS_FILE_NAME
            target.write_text(json.dumps(beacons, separators=(",", ":")))
            print(f"wrote {target}: {len(beacons['rows'])} junction beacons")

    if args.bikeshare_trips is not None:
        # Capital Bikeshare's trips, routed into the popular corridors at the rebuild
        # (pipeline.bikeshare_corridors). Checked by the rebuild's own reader, so a bad
        # file is refused here, not after the segments are written.
        from pipeline import bikeshare_corridors

        try:
            trips = bikeshare_corridors.load(args.bikeshare_trips)
        except (ValueError, KeyError, TypeError) as error:
            parser.error(f"--bikeshare-trips: {args.bikeshare_trips}: {error}")
        if trips is None:
            parser.error(f"--bikeshare-trips: {args.bikeshare_trips} not found")
        target = reference / bikeshare_corridors.FILE_NAME
        shutil.copyfile(args.bikeshare_trips, target)
        print(f"wrote {target}: {len(trips.docks)} docks, {len(trips.pairs)} dock pairs")

    missing = [name for name in REQUIRED if not (reference / name).exists()]
    for name in missing:
        print(f"MISSING {reference / name}; the rebuild will refuse to run", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
