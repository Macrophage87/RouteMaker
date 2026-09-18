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
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import osmium
from django.contrib.gis.geos import MultiPolygon, Polygon

from pipeline import source as source_module
from pipeline.elevation import HGT_1ARCSEC_SIDE, TileName
from pipeline.run import ADMIN_AND_TIMEZONE_TABLES
from pipeline.tiles import CommandOutput

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
        # `lit=24/7` is on the road deliberately. It is one of the four values
        # upstream reads as lit (lua/vendor/graph_upstream.lua:414-423) that a
        # `== "yes"` derivation calls unlit, and the whole point of it being on a
        # way the end-to-end tests already follow through the pipeline is that
        # both consumers - the `rm:lit` tag and the segment column - are read
        # back from a real rebuild rather than from a unit test of the mapping.
        road_tags = {
            "highway": "secondary",
            "maxspeed": "35 mph",
            "name": "Test Road",
            "lit": "24/7",
        }
        if changed:
            road_tags = {
                "highway": "residential",
                "maxspeed": "20 mph",
                "name": "Test Road",
                "lit": "24/7",
            }
        writer.add_way(osmium.osm.mutable.Way(id=100, nodes=[1, 2], version=1, tags=road_tags))
        writer.add_way(
            osmium.osm.mutable.Way(
                id=200,
                nodes=[3, 4],
                version=1,
                # And the other direction: `disused` is a value upstream reads as
                # *not* lit, which a `!= "no"` derivation would call lit.
                tags={"highway": "cycleway", "name": "Test Trail", "lit": "disused"},
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


def build_named_bridge_extract(path: Path, *, roadway_id: int, sidepath_id: int, name: str) -> None:
    """A bridge's roadway and the shared-use path on it, both carrying the
    bridge's name.

    The ordinary OSM shape for a Potomac crossing with a path on it: the path is
    a separate `highway=cycleway` way, tagged `bridge=yes` like the roadway it
    runs on and named after the same structure, because that is the name the
    structure has. The Woodrow Wilson path, the 14th Street path and the Key
    Bridge sidewalk are all mapped this way.

    It exists so the crossings fixture's `roadway_bicycle_legal` column can be
    driven through the real pipeline against the geometry it has to tell apart,
    rather than against a synthetic row keyed by way id.
    """
    Path(path).unlink(missing_ok=True)  # osmium refuses to overwrite
    writer = osmium.SimpleWriter(str(path))
    try:
        nodes = {
            1: (-77.045, 38.905),
            2: (-77.030, 38.905),
            3: (-77.045, 38.9052),
            4: (-77.030, 38.9052),
        }
        for node_id, (lon, lat) in nodes.items():
            writer.add_node(
                osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags={}, version=1)
            )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=roadway_id,
                nodes=[1, 2],
                version=1,
                tags={"highway": "motorway", "bridge": "yes", "name": name},
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=sidepath_id,
                nodes=[3, 4],
                version=1,
                tags={"highway": "cycleway", "bridge": "yes", "name": name},
            )
        )
    finally:
        writer.close()


def write_reference_data(
    root: Path, *, urban=(), sidepath=(), volume=(), legality=(), crossings=()
) -> Path:
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
    # `crossings` is for rows that have to resolve the way the shipped fixture
    # does - by name, against whatever the extract carries - rather than by an
    # id the test already knows. `sidepath` and `legality` stay id-keyed,
    # because most of these tests are about what the pipeline does with an
    # answer rather than about how it reaches one.
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
            + list(crossings)
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


def fake_download(destination: Path) -> None:
    """One regional Geofabrik extract, minus the network.

    Written under a name osmium's writer recognises and then moved onto the
    `.part` the pipeline asked for, because that writer picks the file format
    from the name. That move is what `curl -o <name>.part` does for real, and
    the point of writing a readable extract here rather than any bytes at all is
    that a rebuild which produces its own extract goes on to read it.
    """
    destination = Path(destination)
    built = destination.with_name("download.osm.pbf")
    build_toy_extract(built)
    built.replace(destination)


def write_sqlite_database(path: Path, table: str, rows: bool = True) -> None:
    """A minimal valid SQLite database with one table in it.

    What `valhalla_build_admins` and `valhalla_build_timezones` leave behind, as
    far as anything here reads it: the build validation opens the file and counts
    rows in the table, so the fake has to write a file `sqlite3` can open rather
    than bytes that begin with the magic number.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT)")
        if rows:
            connection.execute(f"INSERT INTO {table} (name) VALUES ('District of Columbia')")
        connection.commit()
    finally:
        connection.close()


def install_source_extract(directory: Path, build=build_toy_extract, **kwargs) -> Path:
    """A deployment whose extract stage has already run this week.

    Both files FETCH_EXTRACT produces, under the names it produces them under:
    the merged extract `valhalla_build_admins` reads and the clipped one the
    rest of the rebuild reads. Both are new, so the freshness rule reuses them
    and no test that is about a later stage downloads anything.

    The merged file is a copy rather than a different map. What the tests need
    from it is that it is the file the admin build is handed and that it is not
    the clipped one; what osmium would really have taken out of it is osmium's
    business.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    clipped = directory / source_module.CLIPPED_NAME
    build(clipped, **kwargs)
    shutil.copyfile(clipped, directory / source_module.MERGED_NAME)
    return clipped


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
    """Stands in for gdalwarp, valhalla_build_admins, valhalla_build_timezones,
    valhalla_build_tiles, valhalla_build_extract and valhalla_service, and for
    nothing else.

    Each does what the real one would leave on disk - a tile of the right size,
    an admin database, a timezone database, a tile directory, a tile extract -
    and `valhalla_service` answers a trace_attributes request the way a built
    graph would, with the grade and cycle lane this instance was told to report.
    Every call is recorded so a test can assert which config a build or a read
    used.

    The two streams are kept apart, the way the real runner keeps them, and on
    the stream each one really uses. That is not decoration: the earlier version
    returned one string with the log *before* the JSON, which is the one
    arrangement valhalla_service never produces - in one-shot mode it forces
    logging to stderr and writes the response to stdout
    (src/valhalla_service.cc:42-44) - and every validation read raised "Extra
    data" against a real build while this fake kept the suite green.
    """

    def __init__(
        self,
        grade: float = 5.5,
        cycle_lane: str | None = "separated",
        log: str = LUA_LOADED_LOG,
        hgt_side: int = HGT_1ARCSEC_SIDE,
        violations: str = "",
        admin: str = "built",
        timezone: str = "built",
        download: Callable[[Path], None] | None = None,
    ) -> None:
        self.grade = grade
        self.cycle_lane = cycle_lane
        self.log = log
        self.hgt_side = hgt_side
        # What the transform wrote to stderr during the parse. Valhalla's own
        # lines go to stdout under `mjolnir.logging.type: std_out`; the remap's
        # refusals are `io.stderr:write` from inside the Lua.
        self.violations = violations
        # How each database build ends: "built" leaves a SQLite file with a row
        # in the table validation reads, "missing" writes nothing at all,
        # "empty-file" leaves a zero-byte file where the config says the
        # database is - which is what a redirect into a script that died
        # produces - and "no-rows" leaves a valid database whose table is empty,
        # which is what an admin build over an extract with no boundary
        # relations produces. The last two are the cases a size check cannot
        # tell from a built database.
        self.admin = admin
        self.timezone = timezone
        # What a "download" leaves behind. The regional Geofabrik files are toy
        # extracts here, so a rebuild that produces its own extract goes on to
        # read something a real reader can read.
        self.download = download or fake_download
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> CommandOutput:
        command = list(command)
        self.calls.append(command)
        name = Path(command[0]).name
        if name == "gdalwarp":
            Path(command[-1]).write_bytes(b"\0" * (self.hgt_side * self.hgt_side * 2))
            return CommandOutput("", "")
        if name == "curl":
            # `curl -fsSL --retry 3 -o <dest>.part <url>`: the regional extract
            # download, minus the network.
            self.download(Path(command[command.index("-o") + 1]))
            return CommandOutput("", "")
        if name == "osmium":
            # `merge` puts the regional files together and `extract` clips the
            # result; both write the file named by `-o`. Copying the first input
            # is enough here - what these commands do to OSM data is osmium's
            # business, and what the pipeline has to get right is which file
            # each one reads and writes.
            destination = Path(command[command.index("-o") + 1])
            inputs = [
                Path(argument)
                for argument in command[2:]
                if argument.endswith(".osm.pbf") and Path(argument) != destination
            ]
            assert inputs, command
            shutil.copyfile(inputs[0], destination)
            return CommandOutput("", "")
        if name == "valhalla_build_admins":
            config = json.loads(Path(command[2]).read_text())
            self.make_database(Path(config["mjolnir"]["admin"]), "admin", self.admin)
            return CommandOutput("", "")
        if name == "sh":
            # The timezone build: a shell script with no arguments whose output
            # is its stdout, so the pipeline redirects it. The destination is
            # read back off the `mv` that puts it in place, which is the
            # pipeline's own way of not leaving a truncated file behind.
            assert "valhalla_build_timezones" in command[-1], command
            destination = command[-1].rsplit(" ", 1)[-1]
            self.make_database(Path(destination), "timezone", self.timezone)
            return CommandOutput("", "downloading timezone polygon file.\n")
        if name == "cp":
            source, destination = Path(command[1]), Path(command[2])
            if source.exists():
                destination.write_bytes(source.read_bytes())
            return CommandOutput("", "")
        if name == "valhalla_build_tiles":
            config = json.loads(Path(command[2]).read_text())
            tile_dir = Path(config["mjolnir"]["tile_dir"])
            tile_dir.mkdir(parents=True, exist_ok=True)
            (tile_dir / "0").mkdir(exist_ok=True)
            (tile_dir / "0" / "003.gph").write_bytes(b"tile")
            return CommandOutput(self.log, self.violations)
        if name == "valhalla_build_extract":
            config = json.loads(Path(command[2]).read_text())
            Path(config["mjolnir"]["tile_extract"]).write_bytes(b"tar")
            return CommandOutput("", "")
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
            # Response on stdout, log on stderr, which is the only arrangement
            # one-shot mode produces. The two log lines are the ones a real
            # read always emits: the extract's tile count
            # (src/baldr/graphreader.cc:110) and the traffic extract every
            # generated config names and no deployment has (:158-159).
            return CommandOutput(
                json.dumps({"edges": [edge], "units": "kilometers"}),
                "2026/09/17 [INFO] Tile extract successfully loaded with tile count: 12\n"
                "2026/09/17 [WARN] Traffic tile extract could not be loaded\n",
            )
        raise AssertionError(f"the pipeline ran a binary the tests do not stand in for: {command}")

    def make_database(self, path: Path, key: str, state: str) -> None:
        """Leave what this instance was told the database build leaves.

        A real SQLite file, because validation queries the table upstream's
        builders create rather than weighing the file: `sqlite3` is what reads
        it, and a fake writing a magic-number prefix would pass a size check and
        fail every real one.
        """
        if state == "missing":
            return
        if state == "empty-file":
            path.write_bytes(b"")
            return
        write_sqlite_database(path, ADMIN_AND_TIMEZONE_TABLES[key], rows=state != "no-rows")

    def commands(self, name: str) -> list[list[str]]:
        return [c for c in self.calls if Path(c[0]).name == name]
