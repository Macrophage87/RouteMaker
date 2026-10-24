// The rail stations' layers, run against a stand-in map that keeps its layers in
// draw order the way MapLibre does (addLayer with a beforeId inserts under it).
import { test } from "node:test";
import assert from "node:assert/strict";
import { addStressOverlay, type OverlayMap } from "./mapGlue.ts";
import {
  ELEVATOR_ICON,
  ELEVATOR_MIN_ZOOM,
  ENTRANCE_MIN_ZOOM,
  NAME_MIN_ZOOM,
  RAIL_LAYERS,
  RAIL_SOURCE_ID,
  ROUTE_BOTTOM_LAYER,
  BASEMAP_POIS_LAYER,
  basemapPoisFilter,
  addRailStations,
  railHitFrom,
  railLayers,
  setRailVisibility,
  stationNear,
  type RailMap,
} from "./railLayer.ts";
import { readFileSync } from "node:fs";
import { OPENING_ZOOM } from "./mapStyle.ts";
import { STATION_MIN_ZOOM, railImages } from "./railLayer.ts";
import { stationsFromTexts, RAIL_FIXTURE_FILES, type RailTexts } from "./railFixtures.ts";
import { PENN_COLOUR, iconId, iconShape, lineStyle, visibleLines, railFeatures, stationMapName, type Station } from "./railStations.ts";

function fakeMap(initial: Array<{ id: string; type: string }>) {
  const layers = [...initial];
  const sources = new Map<string, { data?: unknown; setData?: (d: unknown) => void }>();
  const images = new Map<string, { width: number; height: number; pixelRatio: number }>();
  const map: RailMap & OverlayMap = {
    getSource: (id) => sources.get(id),
    addSource: (id: string, source: { data?: unknown }) => {
      const entry = { ...source, setData: (d: unknown) => (entry.data = d) };
      sources.set(id, entry);
    },
    getStyle: () => ({ layers }),
    addLayer: (layer: object, before?: string) => {
      const l = layer as { id: string; type: string };
      if (before === undefined) {
        layers.push(l);
        return;
      }
      // As MapLibre does: a beforeId that is not on the map is an error.
      const at = layers.findIndex((x) => x.id === before);
      if (at < 0) throw new Error(`no layer ${before}`);
      layers.splice(at, 0, l);
    },
    getLayer: (id) => layers.find((l) => l.id === id),
    setLayoutProperty: () => {},
    hasImage: (id) => images.has(id),
    addImage: (id, image, options) => {
      assert.equal(image.data.length, image.width * image.height * 4, id);
      images.set(id, { width: image.width, height: image.height, pixelRatio: options.pixelRatio });
    },
  };
  return { map, layers, sources, images };
}

const BASE = [
  { id: "earth", type: "fill" },
  { id: "roads", type: "line" },
  { id: "road-labels", type: "symbol" },
  { id: "places", type: "symbol" },
];
const ROUTE = [
  { id: ROUTE_BOTTOM_LAYER, type: "line" },
  { id: "route-line", type: "line" },
];

const station = (id: string, metro: Station["metro"], penn: boolean, elevators: Station["elevators"] = []): Station => ({
  id,
  name: id,
  point: [-77, 38.9],
  metro,
  penn,
  elevators,
  osmElevators: [],
  entrances: [[-77.0005, 38.9]],
});
const STATIONS = [
  station("a", ["red", "blue"], false, [[-77.001, 38.9]]),
  station("b", ["red"], true),
  station("c", [], true),
];
const ALL = { metro: true, marc: true };

test("the stations go over the base map and its labels, directly under the route", () => {
  const { map, layers } = fakeMap([...BASE, ...ROUTE]);
  assert.equal(addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2), true);
  const ids = layers.map((l) => l.id);
  assert.deepEqual(ids, [
    ...BASE.map((l) => l.id),
    RAIL_LAYERS.entrances,
    RAIL_LAYERS.stations,
    RAIL_LAYERS.names,
    RAIL_LAYERS.elevators,
    RAIL_LAYERS.badges,
    ...ROUTE.map((l) => l.id),
  ]);
});

test("the stress overlay, added after them (it waits on its endpoint), still goes under them", () => {
  const { map, layers } = fakeMap([...BASE, ...ROUTE]);
  addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2);
  addStressOverlay(map, "https://example.test", true);
  const ids = layers.map((l) => l.id);
  const lastStress = Math.max(...ids.map((id, i) => (id.startsWith("stress") ? i : -1)));
  assert.ok(lastStress >= 0);
  assert.ok(lastStress < ids.indexOf(RAIL_LAYERS.entrances), ids.join(" "));
  assert.ok(ids.indexOf(RAIL_LAYERS.elevators) < ids.indexOf(ROUTE_BOTTOM_LAYER));
});

test("the stations are added once, with an icon for every line combination and the elevator", () => {
  const { map, images, layers } = fakeMap([...BASE, ...ROUTE]);
  addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2);
  const count = layers.length;
  assert.equal(addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2), false);
  assert.equal(layers.length, count);
  for (const lines of [["red", "blue"], ["red", "penn"], ["red"], ["penn"]] as const) {
    assert.ok(images.has(iconId(lines)), iconId(lines));
  }
  assert.ok(images.has(ELEVATOR_ICON));
  for (const image of images.values()) assert.equal(image.pixelRatio, 2);
});

test("the layers read the source's features by kind, and the station icon by its own property", () => {
  const layers = railLayers();
  const kind = (id: string) => (layers.find((l) => l.id === id) as { filter: unknown }).filter;
  assert.deepEqual(kind(RAIL_LAYERS.stations), ["==", ["get", "kind"], "station"]);
  assert.deepEqual(kind(RAIL_LAYERS.elevators), ["==", ["get", "kind"], "elevator"]);
  assert.deepEqual(kind(RAIL_LAYERS.entrances), ["==", ["get", "kind"], "entrance"]);
  for (const layer of layers) assert.equal(layer.source, RAIL_SOURCE_ID);
  const stations = layers.find((l) => l.id === RAIL_LAYERS.stations) as { layout: Record<string, unknown> };
  assert.deepEqual(stations.layout["icon-image"], ["get", "icon"]);
  assert.deepEqual(stations.layout["symbol-sort-key"], ["get", "sort"]);
  assert.equal(stations.layout["text-field"], undefined, "the names are their own layer");
  assert.deepEqual(kind(RAIL_LAYERS.names), ["==", ["get", "kind"], "station"]);
  const names = layers.find((l) => l.id === RAIL_LAYERS.names) as { minzoom: number; layout: Record<string, unknown> };
  assert.deepEqual(names.layout["text-field"], ["get", "name"]);
  assert.equal(names.minzoom, NAME_MIN_ZOOM);
});

test("elevators come in at street zoom and plain entrances later, de-emphasised", () => {
  const layers = railLayers() as Array<{ id: string; minzoom?: number; paint?: Record<string, unknown> }>;
  const by = (id: string) => layers.find((l) => l.id === id)!;
  assert.equal(by(RAIL_LAYERS.elevators).minzoom, ELEVATOR_MIN_ZOOM);
  assert.equal(by(RAIL_LAYERS.entrances).minzoom, ENTRANCE_MIN_ZOOM);
  assert.ok(ENTRANCE_MIN_ZOOM > ELEVATOR_MIN_ZOOM);
  assert.ok((by(RAIL_LAYERS.entrances).paint?.["circle-opacity"] as number) < 1);
  assert.ok((by(RAIL_LAYERS.stations).minzoom ?? 0) < ELEVATOR_MIN_ZOOM);
});

test("the toggles replace what the source holds", () => {
  const { map, sources } = fakeMap([...BASE, ...ROUTE]);
  addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2);
  const stationsIn = () =>
    (sources.get(RAIL_SOURCE_ID)?.data as { features: Array<{ properties: { kind: string; id: string } }> }).features
      .filter((f) => f.properties.kind === "station")
      .map((f) => f.properties.id);
  assert.deepEqual(stationsIn(), ["a", "b", "c"]);
  setRailVisibility(map, STATIONS, { metro: false, marc: true });
  assert.deepEqual(stationsIn(), ["b", "c"]);
  setRailVisibility(map, STATIONS, { metro: true, marc: false });
  assert.deepEqual(stationsIn(), ["a", "b"]);
  setRailVisibility(map, STATIONS, { metro: false, marc: false });
  assert.deepEqual(stationsIn(), []);
});

test("added before the route exists, the stations go on top rather than failing", () => {
  const { map, layers } = fakeMap(BASE);
  addRailStations(map, STATIONS, ALL, PENN_COLOUR, 1);
  assert.deepEqual(
    layers.slice(-5).map((l) => l.id),
    [RAIL_LAYERS.entrances, RAIL_LAYERS.stations, RAIL_LAYERS.names, RAIL_LAYERS.elevators, RAIL_LAYERS.badges],
  );
});

test("a tap names the station, or the elevator tapped and where it is", () => {
  assert.equal(railHitFrom([]), null);
  assert.equal(railHitFrom([{ properties: { kind: "entrance", id: "a" } }]), null);
  assert.deepEqual(railHitFrom([{ properties: { kind: "station", id: "a" } }]), { id: "a" });
  assert.deepEqual(
    railHitFrom([
      { properties: { kind: "elevator", id: "a" }, geometry: { type: "Point", coordinates: [-77.001, 38.9] } },
      { properties: { kind: "station", id: "a" } },
    ]),
    { id: "a", elevator: [-77.001, 38.9] },
  );
  assert.equal(railHitFrom([{ properties: { kind: "station" } }]), null, "a feature with no id is not a station");
});

const texts = Object.fromEntries(
  Object.entries(RAIL_FIXTURE_FILES).map(([key, file]) => [
    key,
    readFileSync(new URL(`../rail-data/${file}`, import.meta.url), "utf8"),
  ]),
) as RailTexts;
const REAL = stationsFromTexts(texts);

test("every station's icon is its lines' colours, wedge by wedge in order; only a MARC-only one is square", () => {
  const images = new Map(railImages(REAL, PENN_COLOUR, 2).map((i) => [i.id, i.raster]));
  for (const station of REAL) {
    for (const visibility of [ALL, { metro: true, marc: false }, { metro: false, marc: true }]) {
      const lines = visibleLines(station, visibility);
      if (lines.length === 0) continue;
      const r = images.get(iconId(lines));
      assert.ok(r, `${station.name}: no icon ${iconId(lines)}`);
      const c = r.width / 2;
      lines.forEach((line, k) => {
        const a = (2 * Math.PI * (k + 0.5)) / lines.length;
        const x = Math.floor(c + 0.5 * c * Math.sin(a));
        const y = Math.floor(c - 0.5 * c * Math.cos(a));
        const i = (y * r.width + x) * 4;
        const hex = `#${[...r.data.slice(i, i + 3)].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
        assert.equal(hex, lineStyle(line, PENN_COLOUR).color.toLowerCase(), `${station.name} wedge ${k}`);
      });
      const corner = Math.floor(r.width * 0.1);
      const opaque = r.data[(corner * r.width + corner) * 4 + 3] > 0;
      assert.equal(opaque, iconShape(lines) === "square", `${station.name} shape`);
      assert.equal(iconShape(lines) === "square", lines.every((l) => l === "penn"));
    }
  }
});

test("the stations show from the zoom the map opens at, and are never hidden by a collision", () => {
  assert.ok(STATION_MIN_ZOOM <= OPENING_ZOOM);
  const layer = railLayers().find((l) => l.id === RAIL_LAYERS.stations) as { layout: Record<string, unknown> };
  assert.equal(layer.layout["icon-allow-overlap"], true);
  assert.equal(layer.layout["icon-ignore-placement"], true);
  assert.equal(layer.layout["text-field"], undefined, "a name that does not fit must not take its icon with it");
});

test("a tap the rendered-feature query misses finds the nearest shown station within reach", () => {
  // MERGE-TILES re-check SHOULD_FIX 1: with the overlay on, a cold page's
  // query missed a station right under the tap; its own point does not.
  const station = (id: string, point: [number, number], metro: string[], penn = false) =>
    ({ id, name: id, point, metro, penn, elevators: [], osmElevators: [], entrances: [] }) as unknown as Station;
  const stations = [
    station("a", [0, 0], ["red"]),
    station("b", [4, 0], ["red"]),
    station("marc", [0, 3], [], true),
  ];
  const project = ([x, y]: [number, number]) => ({ x, y });
  const all = { metro: true, marc: true };
  assert.deepEqual(stationNear(stations, all, project, { x: 1, y: 0 }, 6), { id: "a" });
  assert.deepEqual(stationNear(stations, all, project, { x: 3, y: 0 }, 6), { id: "b" }, "the nearest");
  assert.deepEqual(stationNear(stations, all, project, { x: 0, y: 2.9 }, 6), { id: "marc" });
  assert.equal(stationNear(stations, all, project, { x: 20, y: 20 }, 6), null, "out of reach");
  assert.deepEqual(stationNear(stations, all, project, { x: 0, y: 6 }, 3), { id: "marc" }, "at the edge of reach");
  assert.equal(stationNear(stations, all, project, { x: 0, y: 6.1 }, 3), null);
  const noMarc = { metro: true, marc: false };
  assert.deepEqual(stationNear(stations, noMarc, project, { x: 0, y: 2.9 }, 6), { id: "a" }, "a hidden station is not tapped");
});

test("stationAt falls back to the stations' points when the query misses, from the zoom they show", () => {
  const source = readFileSync(new URL("../railInteraction.ts", import.meta.url), "utf8");
  assert.match(
    source,
    /if \(!hit && map\.getLayer\(RAIL_LAYERS\.stations\) && map\.getZoom\(\) >= STATION_MIN_ZOOM\) \{\s*hit = stationNear\(options\.stations, options\.visibility\(\), \(p\) => map\.project\(p\), point, TAP_SLOP\);/,
  );
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /stations: RAIL_STATIONS,/);
});

test("station names are larger than the street names, in a ride too, and show from city zoom", async () => {
  const { ROAD_LABEL } = await import("../stressStyle.js");
  const { NAME_MIN_ZOOM, RIDE_STATION_NAME_SIZE, STATION_NAME_SIZE } = await import("./railLayer.ts");
  const layer = railLayers().find((l) => l.id === RAIL_LAYERS.names) as { layout: Record<string, unknown>; paint: Record<string, unknown> };
  assert.equal(layer.layout["text-size"], STATION_NAME_SIZE);
  assert.equal(STATION_NAME_SIZE, 18);
  assert.equal(RIDE_STATION_NAME_SIZE, 24);
  assert.ok(STATION_NAME_SIZE > ROAD_LABEL.size && RIDE_STATION_NAME_SIZE > ROAD_LABEL.rideSize);
  assert.equal(layer.paint["text-halo-width"], ROAD_LABEL.haloWidth);
  // From city zoom, not region zoom, where they ran together.
  assert.equal(NAME_MIN_ZOOM, 12);
  assert.ok(NAME_MIN_ZOOM > OPENING_ZOOM && NAME_MIN_ZOOM < ELEVATOR_MIN_ZOOM);
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(mapView, /RIDE_STATION_NAME_SIZE : STATION_NAME_SIZE/, "a ride switches the station names' size");
  assert.match(mapView, /stationNamesTarget\(map\.getLayersOrder\(\)\)/, "the names are kept over the other layers");
});

test("where names crowd, the station with most lines keeps its name and a closed one gives way", () => {
  const layer = railLayers().find((l) => l.id === RAIL_LAYERS.names) as { layout: Record<string, unknown> };
  // MapLibre places the lower key first; the key is minus the feature's sort (railStations.ts: lines, 0 when closed).
  assert.deepEqual(layer.layout["symbol-sort-key"], ["-", 0, ["get", "sort"]]);
  const at = (sort: number) => 0 - sort;
  assert.ok(at(4) < at(2) && at(2) < at(1) && at(1) < at(0));
});

test("a tap on a station's icon opens that station, though a neighbour's name covers it", () => {
  const name = { layer: { id: RAIL_LAYERS.names }, properties: { kind: "station", id: "metro-center" } };
  const icon = { layer: { id: RAIL_LAYERS.stations }, properties: { kind: "station", id: "gallery-place" } };
  assert.deepEqual(railHitFrom([name, icon]), { id: "gallery-place" });
  // A name alone still opens its station.
  assert.deepEqual(railHitFrom([name]), { id: "metro-center" });
  // The icons draw interchanges on top; their names are placed first where they crowd.
  const layers = railLayers() as Array<{ id: string; layout?: Record<string, unknown> }>;
  const key = (id: string) => layers.find((l) => l.id === id)?.layout?.["symbol-sort-key"];
  assert.deepEqual([key(RAIL_LAYERS.stations), key(RAIL_LAYERS.names)], [["get", "sort"], ["-", 0, ["get", "sort"]]]);
});

test("the station names go over every layer but the hazard marks, the ride dots and Review's, and then stay", async () => {
  const { stationNamesTarget } = await import("./railLayer.ts");
  const names = RAIL_LAYERS.names;
  // Over the pins and the route.
  assert.deepEqual(stationNamesTarget(["base", names, "water-restrooms", "route-casing", "route-line"]), { before: undefined });
  // Under the hazard marks and the ride dots.
  assert.deepEqual(stationNamesTarget([names, "route-line", "route-hazard-marks", "ride-dots-dot"]), { before: "route-hazard-marks" });
  // Once there, no move, so its styledata cannot loop.
  assert.equal(stationNamesTarget(["route-line", names, "route-hazard-marks", "route-hazard-marks-along"]), null);
  assert.equal(stationNamesTarget(["route-line", names]), null);
  assert.equal(stationNamesTarget(["route-line", "review-dots", names]) !== null, true);
});

// One name per station (the owner, 2026-10-21: "Metros are sometimes written twice"): the base map's `pois` layer,
// filter as the shipped package writes it, run by MapLibre's own filter code on a z14 tile's points.
test("the base map no longer names a station the map names itself, and still names every other", async () => {
  const spec = await import("@maplibre/maplibre-gl-style-spec");
  const { layers: protomapsLayers, namedFlavor } = await import("@protomaps/basemaps");
  const pois = (protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Array<{ id: string; filter?: unknown }>).find(
    (layer) => layer.id === BASEMAP_POIS_LAYER,
  );
  assert.ok(pois, "the base map still has its pois layer");
  const shadyGrove = REAL.find((s) => s.name === "Shady Grove");
  assert.ok(shadyGrove);
  const z = 14;
  const tileOf = ([lon, lat]: [number, number]) => {
    const n = 2 ** z;
    const x = ((lon + 180) / 360) * n;
    const y = ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * n;
    return { x, y };
  };
  const shows = (filter: unknown, kind: string, at: [number, number]) => {
    const { x, y } = tileOf(at);
    const canonical = { z, x: Math.floor(x), y: Math.floor(y) };
    const point = { x: Math.round((x % 1) * 8192), y: Math.round((y % 1) * 8192) };
    const feature = { type: 1, properties: { kind, name: "x", min_zoom: 10 }, geometry: [[point]] };
    return spec.featureFilter(filter as never, "layers[pois].filter").filter({ zoom: z }, feature as never, canonical);
  };
  const [lon, lat] = shadyGrove.point;
  const near: [number, number] = [lon + 0.001, lat + 0.001]; // ~130 m off, as an OSM node on the platform
  const far: [number, number] = [lon + 0.02, lat]; // ~1 mi east
  const filter = basemapPoisFilter(pois.filter, REAL, ALL);
  const style = {
    version: 8,
    sources: { protomaps: { type: "vector", tiles: ["https://example.invalid/{z}/{x}/{y}.pbf"] } },
    layers: [{ ...pois, filter }],
  };
  assert.deepEqual(spec.validateStyleMin(style as never).map((e) => e.message), [], "a valid filter");
  assert.equal(shows(pois.filter, "station", near), true, "named twice before");
  assert.equal(shows(filter, "station", near), false, "the base map's name is gone");
  assert.equal(shows(filter, "station", far), true, "a station we do not draw keeps its name");
  assert.equal(shows(filter, "park", near), true, "the park beside it keeps its name");
  // A toggle off hands the name back to the base map.
  assert.equal(shows(basemapPoisFilter(pois.filter, REAL, { metro: false, marc: true }), "station", near), true);
  assert.equal(basemapPoisFilter(pois.filter, REAL, { metro: false, marc: false }), pois.filter);
  // An airport its station names (the owner, 2026-10-23: "This one is redunant as well, since we have labels for each").
  const dca = REAL.find((s) => s.name === "Ronald Reagan Washington National Airport")!;
  const airfield: [number, number] = [dca.point[0] + 0.008, dca.point[1] - 0.004]; // the base map's label, ~0.5 mi off
  assert.equal(shows(pois.filter, "aerodrome", airfield), true, "named twice before");
  assert.equal(shows(filter, "aerodrome", airfield), false, "the station names it");
  assert.equal(shows(filter, "aerodrome", [-76.9223, 38.9806]), true, "College Park Airport, no station, keeps its name");
  assert.equal(shows(filter, "station", airfield), true, "the reach is the airport's alone");
});

test("National Airport's station is labelled as DC says it, and keeps WMATA's name everywhere else", () => {
  const dca = REAL.find((s) => s.name === "Ronald Reagan Washington National Airport")!;
  assert.equal(stationMapName(dca), "National Airport (DCA)");
  const feature = railFeatures([dca], ALL).features.find((f) => f.properties.kind === "station")!;
  assert.equal(feature.properties.name, "National Airport (DCA)");
  const other = REAL.find((s) => s.name === "Shady Grove")!;
  assert.equal(stationMapName(other), "Shady Grove");
});

test("the stations set the base map's pois filter, and the toggles reset it from the original", () => {
  const { map } = fakeMap([...BASE, { id: BASEMAP_POIS_LAYER, type: "symbol" }, ...ROUTE]);
  const original = ["==", "kind", "station"];
  const filters = new Map<string, unknown>([[BASEMAP_POIS_LAYER, original]]);
  map.getFilter = (id) => filters.get(id);
  map.setFilter = (id, filter) => filters.set(id, filter);
  addRailStations(map, STATIONS, ALL, PENN_COLOUR, 2);
  assert.deepEqual(filters.get(BASEMAP_POIS_LAYER), basemapPoisFilter(original, STATIONS, ALL));
  setRailVisibility(map, STATIONS, { metro: false, marc: false });
  assert.equal(filters.get(BASEMAP_POIS_LAYER), original);
  setRailVisibility(map, STATIONS, { metro: true, marc: false });
  assert.deepEqual(filters.get(BASEMAP_POIS_LAYER), basemapPoisFilter(original, STATIONS, { metro: true, marc: false }));
});
