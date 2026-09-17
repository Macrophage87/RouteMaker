"""What the rebuild tests share: a toy extract, the region's state polygons,
and a stand-in for the binaries the pipeline shells out to.

The stand-in is the only thing the end-to-end tests fake. Everything else -
the handler set, the samplers, the schema writes, the promotion, the settings
table, the drift report - is the production code called the way the weekly
task calls it. A test that faked more than the binaries would be testing its
own reflection, which is the failure three rounds of review found.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import osmium
from django.contrib.gis.geos import MultiPolygon, Polygon

from pipeline.elevation import HGT_3ARCSEC_SIDE, TileName

REPO = Path(__file__).resolve().parents[1]
LUA_LOADED_LOG = "... Using LUA script: /conf/lua/graph.lua ..."
GIB = 1024**3


def build_toy_extract(path: Path, *, changed: bool = False) -> None:
    """A road crossing the District line, a trail, and a farm track.

    `changed` is next week's map: the farm track has gone and the road has
    been re-signed to 20 mph, which is what the drift report should notice.
    """
    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (-77.02, 38.90),
            2: (-76.98, 38.90),  # crosses -77.00
            3: (-77.04, 38.91),
            4: (-77.03, 38.91),  # trail, inside DC
            5: (-77.045, 38.92),
            6: (-77.035, 38.92),  # track
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        road_tags = {"highway": "secondary", "maxspeed": "35 mph", "name": "Test Road"}
        if changed:
            road_tags = {"highway": "residential", "maxspeed": "20 mph", "name": "Test Road"}
        writer.add_way(osmium.osm.mutable.Way(id=100, nodes=[1, 2], version=1, tags=road_tags))
        writer.add_way(
            osmium.osm.mutable.Way(
                id=200, nodes=[3, 4], version=1, tags={"highway": "cycleway", "name": "Test Trail"}
            )
        )
        if not changed:
            writer.add_way(
                osmium.osm.mutable.Way(
                    id=300,
                    nodes=[5, 6],
                    version=1,
                    tags={"highway": "track", "surface": "gravel", "tracktype": "grade2"},
                )
            )
        # A path e-bikes are barred from, and a bridge whose only bike provision
        # is a sidewalk.
        writer.add_way(
            osmium.osm.mutable.Way(
                id=400,
                nodes=[3, 4],
                version=1,
                tags={"highway": "path", "electric_bicycle": "no"},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=500,
                nodes=[5, 6],
                version=1,
                tags={"highway": "trunk", "bridge": "yes", "name": "Sidepath Bridge"},
            )
        )
    finally:
        writer.close()


def box(west: float, east: float, south: float = 38.85, north: float = 38.95) -> MultiPolygon:
    return MultiPolygon(
        Polygon(((west, south), (east, south), (east, north), (west, north), (west, south)))
    )


def state_polygons():
    """The state and police layers for the toy region. Wrapped as a fixture
    by each test module that needs it: pytest discovers fixtures per module,
    and importing one by name reads as a redefinition."""
    from core.models import Jurisdiction

    Jurisdiction.objects.all().delete()
    Jurisdiction.objects.create(
        layer="police", name="MPD", state="DC", geometry=box(-77.10, -77.00)
    )
    Jurisdiction.objects.create(
        layer="police", name="Arlington", state="VA", geometry=box(-77.00, -76.90)
    )
    # The state layer the border inserter resolves against. Querying every layer
    # let a park polygon answer and made the result non-deterministic.
    Jurisdiction.objects.create(
        layer="state", name="District of Columbia", state="DC", geometry=box(-77.10, -77.00)
    )
    Jurisdiction.objects.create(
        layer="state", name="Virginia", state="VA", geometry=box(-77.00, -76.90)
    )
    yield
    Jurisdiction.objects.all().delete()


def write_reference_data(root: Path, *, urban=(), sidepath=(), volume=(), legality=()) -> Path:
    """The reference inputs the rebuild refuses to run without.

    `legality` is {way id: roadway bicycle legal}, the other half of the
    crossings fixture: a row that says nothing about `sidepath_only` but does
    say whether OSM's `bicycle` tag bars the roadway outright. The two columns
    are deliberately separable here, because in the fixture this file used to
    ship with they were perfectly correlated and OR-ing them together tested
    green while being inert.
    """
    directory = root / "reference"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "urban-areas.json").write_text(json.dumps(list(urban)))
    (directory / "crossings.json").write_text(
        json.dumps(
            [
                {"osm_way_id": way_id, "sidepath_only": True, "roadway_bicycle_legal": False}
                for way_id in sidepath
            ]
            + [
                {"osm_way_id": way_id, "sidepath_only": False, "roadway_bicycle_legal": legal}
                for way_id, legal in dict(legality).items()
            ]
        )
    )
    (directory / "volume.json").write_text(json.dumps(list(volume)))
    return directory


def build_parallel_extract(path: Path, *, road_id: int, trail_id: int) -> None:
    """A road and a shared-use path running alongside it, with one count line
    drawn between them and slightly nearer the path.

    The Mount Vernon Trail / GW Parkway geometry, in miniature: the trail sits
    15 m from the roadway, well inside `conflation.MAX_SEPARATION_M`, and an
    agency survey line is not drawn to the centreline. So the path can out-rank
    the roadway on distance alone, and exclusivity then denies the count to the
    roadway as well - the whole count lost to a way that carries no motor
    traffic at all.

    Both ids are parameters so a test can put either way first in the file,
    which is the order `read_ways` produces and the order `conflate` sees.
    """
    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        # ~15 m and ~9 m north of the roadway, at this latitude.
        road_lat, trail_lat = 38.9000, 38.900135
        nodes = {
            1: (-77.020, road_lat),
            2: (-77.002, road_lat),
            3: (-77.020, trail_lat),
            4: (-77.002, trail_lat),
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        ways = {
            road_id: (
                [1, 2],
                {"highway": "primary", "maxspeed": "45 mph", "name": "Parkway"},
            ),
            trail_id: ([3, 4], {"highway": "cycleway", "name": "Riverside Trail"}),
        }
        for way_id in sorted(ways):
            node_ids, tags = ways[way_id]
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=node_ids, version=1, tags=tags))
    finally:
        writer.close()


PARALLEL_COUNT = {
    "id": "count-parkway",
    # Drawn between the two ways and nearer the trail, which is what makes the
    # trail the better candidate on geometry alone.
    "coordinates": [[-77.021, 38.90008], [-77.001, 38.90008]],
    "aadt": 24000,
    "source": "state",
    "year": 2025,
}


def fake_fetch(tile: TileName, into: Path) -> Path:
    """The 3DEP download, minus the network."""
    into.mkdir(parents=True, exist_ok=True)
    source = into / f"USGS_1_{tile.stem.lower()}.tif"
    source.write_bytes(b"not a real GeoTIFF")
    return source


def roomy_disk(path: str):
    """A data volume with plenty of room. The gate's own test tightens it."""
    return shutil._ntuple_diskusage(total=1000 * GIB, used=100 * GIB, free=900 * GIB)


class FakeBinaries:
    """Stands in for gdalwarp, valhalla_build_tiles, valhalla_build_extract and
    valhalla_service, and for nothing else.

    Each does what the real one would leave on disk - a tile of the right size,
    a tile directory, a tile extract - and `valhalla_service` answers a
    trace_attributes request the way a built graph would, with the grade and
    cycle lane this instance was told to report. Every call is recorded so a
    test can assert which config a build or a read used.
    """

    def __init__(
        self,
        grade: float = 5.5,
        cycle_lane: str | None = "separated",
        log: str = LUA_LOADED_LOG,
        hgt_side: int = HGT_3ARCSEC_SIDE,
    ) -> None:
        self.grade = grade
        self.cycle_lane = cycle_lane
        self.log = log
        self.hgt_side = hgt_side
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> str:
        command = list(command)
        self.calls.append(command)
        name = Path(command[0]).name
        if name == "gdalwarp":
            Path(command[-1]).write_bytes(b"\0" * (self.hgt_side * self.hgt_side * 2))
            return ""
        if name == "valhalla_build_tiles":
            config = json.loads(Path(command[2]).read_text())
            tile_dir = Path(config["mjolnir"]["tile_dir"])
            tile_dir.mkdir(parents=True, exist_ok=True)
            (tile_dir / "0").mkdir(exist_ok=True)
            (tile_dir / "0" / "003.gph").write_bytes(b"tile")
            return self.log
        if name == "valhalla_build_extract":
            config = json.loads(Path(command[2]).read_text())
            Path(config["mjolnir"]["tile_extract"]).write_bytes(b"tar")
            return ""
        if name == "valhalla_service":
            _config, action, request = command[1:4]
            assert action == "trace_attributes", action
            wanted = json.loads(request)["filters"]["attributes"]
            edge: dict = {"way_id": 100}
            if "edge.weighted_grade" in wanted:
                edge["weighted_grade"] = self.grade
                edge["max_upward_grade"] = self.grade
            if "edge.cycle_lane" in wanted and self.cycle_lane is not None:
                edge["cycle_lane"] = self.cycle_lane
            return "some log line\n" + json.dumps({"edges": [edge], "units": "kilometers"})
        raise AssertionError(f"the pipeline ran a binary the tests do not stand in for: {command}")

    def commands(self, name: str) -> list[list[str]]:
        return [c for c in self.calls if Path(c[0]).name == name]
