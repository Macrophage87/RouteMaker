// The rail stations as the map builds them from the committed fixtures.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { haversineM, type LonLat } from "./geo.ts";
import {
  LINE_KEYS,
  METRO_LINES,
  SHARED_STATION_M,
  allIconLines,
  applyCorrections,
  bikeEntrance,
  buildStations,
  entranceNote,
  stationIndex,
  iconId,
  iconShape,
  linesLabel,
  parseLines,
  placeAtStation,
  railFeatures,
  stationRoles,
  visibleLines,
  type BikeEntrance,
  type LineCorrections,
  type MarcCollection,
  type Station,
} from "./railStations.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../rail-data/${name}`, import.meta.url), "utf8"));
const metro = read("metro-stations.geojson");
const entrances = read("metro-entrances.geojson");
const marc: MarcCollection = read("marc-penn-stations.geojson");
const corrections: LineCorrections = read("metro-line-corrections.json");
const osmElevators = read("metro-osm-elevators.geojson");
const stations = buildStations(metro, entrances, marc, { corrections, osmElevators });
const uncorrected = buildStations(metro, entrances, marc);
const named = (name: string) => {
  const found = stations.find((s) => s.name === name);
  assert.ok(found, name);
  return found;
};
const ALL = { metro: true, marc: true };

// Every LINE value in both DC layers, as they are.
const lineValues = [
  ...new Set(
    [...metro.features, ...entrances.features].map((f: { properties: { LINE: string } }) => f.properties.LINE),
  ),
] as string[];

test("every LINE value in the layers parses to exactly the lines it names, in drawing order", () => {
  assert.ok(lineValues.length >= 15, `${lineValues.length} values`);
  const order = LINE_KEYS as readonly string[];
  for (const value of lineValues) {
    const lines = parseLines(value);
    const words = value.split(",").map((w) => w.trim());
    assert.deepEqual([...lines].sort(), [...new Set(words)].sort(), value);
    const at = lines.map((line) => order.indexOf(line));
    assert.deepEqual([...at].sort((a, b) => a - b), at, `${value}: not in drawing order`);
  }
});

test("the parser takes any order and spacing and each line once", () => {
  assert.deepEqual(parseLines("green, yellow, orange, blue, silver"), ["orange", "blue", "green", "yellow", "silver"]);
  assert.deepEqual(parseLines("silver, blue"), ["blue", "silver"]);
  assert.deepEqual(parseLines("green,yellow"), ["green", "yellow"]);
  assert.deepEqual(parseLines(" Red ,red"), ["red"]);
});

test("a word that is not a line's name, or no line at all, is an error rather than a missing line", () => {
  for (const bad of ["grn", "red, purple", "", " , ", "penn"]) {
    assert.throws(() => parseLines(bad), Error, JSON.stringify(bad));
  }
});

test("the interchanges downtown carry every line that serves them", () => {
  assert.deepEqual(named("Metro Center").metro, ["red", "orange", "blue", "silver"]);
  assert.deepEqual(named("Gallery Pl-Chinatown").metro, ["red", "green", "yellow"]);
  assert.deepEqual(named("L'Enfant Plaza").metro, ["orange", "blue", "green", "yellow", "silver"]);
  assert.deepEqual(named("Rosslyn").metro, ["orange", "blue", "silver"]);
  assert.deepEqual(named("Fort Totten").metro, ["red", "green", "yellow"]);
});

test("Silver to New Carrollton and Yellow to Greenbelt are on top of DC's LINE field", () => {
  assert.deepEqual(visibleLines(named("New Carrollton"), ALL), ["orange", "silver", "penn"]);
  for (const name of ["Minnesota Ave", "Deanwood", "Cheverly", "Landover"]) {
    assert.deepEqual(named(name).metro, ["orange", "silver"], name);
  }
  for (const name of ["Greenbelt", "College Park-U of Md", "Shaw-Howard U", "Columbia Heights"]) {
    assert.deepEqual(named(name).metro, ["green", "yellow"], name);
  }
  // Only the stations the table names change, and each by exactly its lines.
  const named_ = new Map(corrections.changes.flatMap((c) => c.stations.map(([n]) => [n, c.add] as const)));
  for (const [i, station] of uncorrected.entries()) {
    const after = stations[i];
    const added = after.metro.filter((line) => !station.metro.includes(line));
    assert.deepEqual(added, named_.get(station.name) ?? [], station.name);
  }
  // Every correction cites its source and date.
  for (const change of corrections.changes) {
    assert.match(change.source, /^https:\/\/www\.wmata\.com\//);
    assert.match(change.since, /^\d{4}-\d{2}-\d{2}$/);
  }
});

test("a correction that no longer fits the layer stops the build instead of being dropped", () => {
  const fresh = () => buildStations(metro, entrances, marc);
  const one = (name: string, gis: string, add = ["silver"]): LineCorrections => ({
    changes: [{ add, since: "2025-06-22", source: "x", stations: [[name, gis]] }],
  });
  assert.throws(() => applyCorrections(fresh(), one("New Carrollton", "MetroStnFullPt_999")), /matches no station/);
  assert.throws(() => applyCorrections(fresh(), one("New Carollton", "MetroStnFullPt_70")), /matches no station/);
  assert.throws(() => applyCorrections(fresh(), one("New Carrollton", "MetroStnFullPt_70", ["orange"])), /already/);
});

test("every Metro station is on the map once, and the MARC stations that are not Metro's are added", () => {
  const metroOnes = stations.filter((s) => s.metro.length > 0);
  assert.equal(metroOnes.length, metro.features.length);
  assert.equal(new Set(stations.map((s) => s.id)).size, stations.length);
  const marcStations = marc.features.filter((f) => f.properties.kind === "station");
  assert.equal(stations.filter((s) => s.penn).length, marcStations.length);
});

test("Union Station and New Carrollton are one station each, on both systems", () => {
  const shared = stations.filter((s) => s.penn && s.metro.length > 0).map((s) => s.name);
  assert.deepEqual(shared.sort(), ["New Carrollton", "Union Station"]);
  assert.deepEqual(visibleLines(named("Union Station"), ALL), ["red", "penn"]);
  // Nothing else is within the sharing distance of a Metro station.
  for (const s of stations.filter((x) => x.penn && x.metro.length === 0)) {
    for (const m of stations.filter((x) => x.metro.length > 0)) {
      assert.ok(haversineM(s.point, m.point) > SHARED_STATION_M, `${s.name} / ${m.name}`);
    }
  }
});

test("the Penn Line stops at Baltimore Penn Station", () => {
  const penn = stations.filter((s) => s.penn);
  const north = Math.max(...penn.map((s) => s.point[1]));
  assert.equal(penn.find((s) => s.point[1] === north)?.name, "Baltimore Penn Station");
  for (const name of ["Martin State Airport", "Edgewood", "Aberdeen", "Perryville"]) {
    assert.equal(stations.some((s) => s.name === name), false, name);
  }
});

test("every entrance is given to a station, near it and of its name", () => {
  const norm = (s: string) => s.toUpperCase().split(/[^A-Z0-9]+/).filter(Boolean)[0];
  let count = 0;
  for (const feature of entrances.features) {
    const point = feature.geometry.coordinates as LonLat;
    const owner = stations.find((s) =>
      [...s.elevators, ...s.entrances].some((p) => p[0] === point[0] && p[1] === point[1]),
    );
    assert.ok(owner, feature.properties.GIS_ID);
    assert.ok(haversineM(owner.point, point) < 400, `${feature.properties.NAME}: ${haversineM(owner.point, point)} m`);
    assert.equal(norm(feature.properties.NAME), norm(owner.name), `${feature.properties.NAME} -> ${owner.name}`);
    const isElevator = feature.properties.DESCRIPTION === "Metro Station Elevator";
    assert.equal(owner.elevators.some((p) => p === point || (p[0] === point[0] && p[1] === point[1])), isElevator);
    count += 1;
  }
  assert.equal(count, 260);
  assert.equal(stations.reduce((n, s) => n + s.elevators.length, 0), 86, "DC's elevators, all of them");
  // OSM's: MARC's and the fallback fixture's, each node once (Union Station is in both).
  const osmIds = new Set([
    ...marc.features.filter((f) => f.properties.kind === "elevator").map((f) => f.properties.osm),
    ...osmElevators.features.map((f: { properties: { osm: string } }) => f.properties.osm),
  ]);
  assert.equal(stations.reduce((n, s) => n + s.osmElevators.length, 0), osmIds.size);
});

test("OSM's elevators are only at stations DC gives none", () => {
  for (const station of stations) {
    if (station.metro.length > 0 && station.osmElevators.length > 0) {
      assert.equal(station.elevators.length, 0, station.name);
    }
  }
  for (const name of ["Wheaton", "Silver Spring", "Forest Glen", "Potomac Yard", "Union Station"]) {
    assert.ok(named(name).osmElevators.length > 0, name);
  }
});

test("the bike entrance: DC's elevator, else OSM's, else the nearest entrance, else the station", () => {
  const near: LonLat = [-77, 38.9005];
  const station: Station = {
    id: "x",
    name: "X",
    point: [-77, 38.9],
    metro: ["red"],
    penn: false,
    elevators: [[-77, 38.902], near, [-77.003, 38.9]],
    osmElevators: [[-77, 38.9001]],
    entrances: [[-77, 38.90005], [-77, 38.9003]],
  };
  assert.deepEqual(bikeEntrance(station), { point: near, kind: "elevator" }, "DC's, even with OSM's nearer");
  assert.deepEqual(bikeEntrance({ ...station, elevators: [] }), { point: [-77, 38.9001], kind: "osm-elevator" });
  assert.deepEqual(bikeEntrance({ ...station, elevators: [], osmElevators: [] }), {
    point: [-77, 38.90005],
    kind: "entrance",
  });
  assert.deepEqual(bikeEntrance({ ...station, elevators: [], osmElevators: [], entrances: [] }), {
    point: [-77, 38.9],
    kind: "station",
  });
  // Real data.
  const kind = (name: string) => bikeEntrance(named(name)).kind;
  assert.equal(kind("Metro Center"), "elevator");
  for (const name of ["Wheaton", "Silver Spring", "Forest Glen", "Potomac Yard", "Union Station"]) {
    assert.equal(kind(name), "osm-elevator", name);
  }
  assert.equal(kind("Dunn Loring-Merrifield"), "entrance");
  assert.equal(kind("BWI Thurgood Marshall Airport"), "osm-elevator");
  assert.equal(kind("Seabrook"), "station");
  // Every Metro station has at least an entrance: none sends a ride to its centre point.
  for (const s_ of stations.filter((x) => x.metro.length > 0)) assert.notEqual(bikeEntrance(s_).kind, "station", s_.name);
});

test("each kind of bike entrance says so on the card", () => {
  const kinds: Array<BikeEntrance["kind"]> = ["elevator", "osm-elevator", "entrance", "station"];
  assert.equal(new Set(kinds.map(entranceNote)).size, kinds.length);
  assert.match(entranceNote("osm-elevator"), /OpenStreetMap/);
});

test("stationBikeEntrance, by id: the bike entrance's point, or null for an id it does not know", () => {
  const index = stationIndex(stations);
  const metroCenter = named("Metro Center");
  assert.equal(index.station(metroCenter.id), metroCenter);
  assert.deepEqual(index.bikeEntrance(metroCenter.id), bikeEntrance(metroCenter).point);
  assert.ok(metroCenter.elevators.includes(index.bikeEntrance(metroCenter.id)!));
  const seabrook = named("Seabrook");
  assert.deepEqual(index.bikeEntrance(seabrook.id), seabrook.point);
  assert.equal(index.bikeEntrance("metro-nope"), null);
  assert.equal(index.station("metro-nope"), undefined);
});

test("the toggles decide which stations and lines are drawn, entrances with their station", () => {
  const count = (visibility: { metro: boolean; marc: boolean }, kind: string) =>
    railFeatures(stations, visibility).features.filter((f) => f.properties.kind === kind).length;
  const marcCount = stations.filter((s) => s.penn).length;
  assert.equal(count(ALL, "station"), stations.length);
  assert.equal(count({ metro: true, marc: false }, "station"), metro.features.length);
  assert.equal(count({ metro: false, marc: true }, "station"), marcCount);
  assert.equal(railFeatures(stations, { metro: false, marc: false }).features.length, 0);
  const union = (visibility: { metro: boolean; marc: boolean }) =>
    railFeatures(stations, visibility).features.find(
      (f) => f.properties.kind === "station" && f.properties.name === "Union Station",
    )?.properties;
  assert.equal(union(ALL)?.icon, "rail-red-penn");
  assert.equal(union({ metro: true, marc: false })?.icon, "rail-red");
  assert.equal(union({ metro: false, marc: true })?.icon, "rail-penn");
  const elevators = count(ALL, "elevator");
  assert.equal(elevators, stations.reduce((n, s) => n + s.elevators.length + s.osmElevators.length, 0));
  assert.ok(count({ metro: false, marc: true }, "elevator") < elevators);
});

test("a station's features carry what its hover card and icon need", () => {
  const f = railFeatures(stations, ALL).features.find((x) => x.properties.name === "Metro Center")!;
  const props = f.properties as Record<string, unknown>;
  assert.equal(props.lines, "red,orange,blue,silver");
  assert.equal(props.icon, iconId(["red", "orange", "blue", "silver"]));
  assert.equal(props.sort, 4);
  assert.match(String(props.label), /Red.*Orange.*Blue.*Silver/);
});

test("every icon a toggle setting can ask for is one allIconLines makes", () => {
  const made = new Set(allIconLines(stations).map(iconId));
  for (const visibility of [ALL, { metro: true, marc: false }, { metro: false, marc: true }]) {
    for (const f of railFeatures(stations, visibility).features) {
      if (f.properties.kind === "station") assert.ok(made.has(f.properties.icon), f.properties.icon);
    }
  }
});

test("a station on both systems needs its MARC-only icon too, for when Metro is hidden", () => {
  const both: Station = { ...named("Union Station") };
  const ids = allIconLines([both]).map(iconId).sort();
  assert.deepEqual(ids, ["rail-penn", "rail-red", "rail-red-penn"]);
});

test("icons are named by their lines, and only a MARC-only one is square", () => {
  assert.equal(iconId(["red", "green"]), "rail-red-green");
  assert.notEqual(iconId(["red", "green"]), iconId(["green", "red"]));
  assert.equal(iconShape(["penn"]), "square");
  assert.equal(iconShape(["red", "penn"]), "circle");
  assert.equal(iconShape(["red"]), "circle");
});

test("the lines read as words", () => {
  assert.equal(linesLabel(["red"]), "Red line");
  assert.equal(linesLabel(["orange", "blue", "silver"]), "Orange, Blue and Silver lines");
  assert.equal(linesLabel(["red", "penn"]), "Red line and MARC Penn Line");
  assert.equal(linesLabel(["penn"]), "MARC Penn Line");
});

test("the six Metro colours are six different colours", () => {
  const colours = Object.values(METRO_LINES).map((l) => l.color.toLowerCase());
  assert.equal(new Set(colours).size, 6);
  for (const c of colours) assert.match(c, /^#[0-9a-f]{6}$/);
});

test("a station can start a plan, end one that has a start, and be a via once there is a leg", () => {
  assert.deepEqual(stationRoles(0), ["start"]);
  assert.deepEqual(stationRoles(1), ["start", "end"]);
  assert.deepEqual(stationRoles(2), ["start", "end", "via"]);
  assert.deepEqual(stationRoles(25), ["start", "end"]);
});

test("start and end replace the plan's ends; a via goes on the leg it lengthens least", () => {
  const s: LonLat = [-77, 39];
  const a: LonLat = [-77.1, 38.9];
  const b: LonLat = [-76.9, 38.9];
  const c: LonLat = [-76.8, 38.95];
  assert.deepEqual(placeAtStation([], s, "start"), [s]);
  assert.deepEqual(placeAtStation([a], s, "start"), [s]);
  assert.deepEqual(placeAtStation([a, b, c], s, "start"), [s, b, c]);
  assert.deepEqual(placeAtStation([a], s, "end"), [a, s]);
  assert.deepEqual(placeAtStation([a, b, c], s, "end"), [a, b, s]);
  assert.deepEqual(placeAtStation([a, c], b, "via"), [a, b, c]);
  // A role the plan cannot take leaves it as it was.
  assert.deepEqual(placeAtStation([], s, "end"), []);
  assert.deepEqual(placeAtStation([a], s, "via"), [a]);
});

test("how many stations route to each kind of bike entrance (README.md's counts)", () => {
  const counts: Record<string, number> = {};
  for (const station of stations) {
    const { kind } = bikeEntrance(station);
    counts[kind] = (counts[kind] ?? 0) + 1;
  }
  // 64 with DC's elevator; 7 Metro stations with OSM's, and BWI; 27 with an entrance;
  // the six MARC-only stations OSM tags nothing at.
  assert.deepEqual(counts, { elevator: 64, "osm-elevator": 8, entrance: 27, station: 6 });
});

test("a corrected station's lines stay in drawing order", () => {
  const fresh = buildStations(metro, entrances, marc);
  // Ashburn is Silver only, last in drawing order: lines added to it go before.
  const ashburn = fresh.find((s) => s.name === "Ashburn")!;
  assert.deepEqual(ashburn.metro, ["silver"]);
  const gis = ashburn.id.replace(/^metro-/, "");
  applyCorrections(fresh, {
    changes: [{ add: ["orange", "red"], since: "2030-01-01", source: "x", stations: [["Ashburn", gis]] }],
  });
  assert.deepEqual(ashburn.metro, ["red", "orange", "silver"]);
});

test("a MARC station's OSM entrance joins its station's entrances", () => {
  const withEntrance: MarcCollection = {
    features: [
      ...marc.features,
      {
        geometry: { type: "Point", coordinates: [-76.843, 38.9733] },
        properties: { kind: "entrance", station: 2, osm: "node/1" },
      },
    ],
  };
  const seabrook = buildStations(metro, entrances, withEntrance).find((s) => s.name === "Seabrook")!;
  assert.deepEqual(seabrook.entrances, [[-76.843, 38.9733]]);
  assert.deepEqual(bikeEntrance(seabrook), { point: [-76.843, 38.9733], kind: "entrance" });
});
