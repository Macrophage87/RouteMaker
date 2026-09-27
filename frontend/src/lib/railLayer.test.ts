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
  addRailStations,
  railHitFrom,
  railLayers,
  setRailVisibility,
  type RailMap,
} from "./railLayer.ts";
import { iconId, type Station } from "./railStations.ts";

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
  assert.equal(addRailStations(map, STATIONS, ALL, "#bdbadc", 2), true);
  const ids = layers.map((l) => l.id);
  assert.deepEqual(ids, [
    ...BASE.map((l) => l.id),
    RAIL_LAYERS.entrances,
    RAIL_LAYERS.stations,
    RAIL_LAYERS.elevators,
    ...ROUTE.map((l) => l.id),
  ]);
});

test("the stress overlay, added after them (it waits on its endpoint), still goes under them", () => {
  const { map, layers } = fakeMap([...BASE, ...ROUTE]);
  addRailStations(map, STATIONS, ALL, "#bdbadc", 2);
  addStressOverlay(map, "https://example.test", true);
  const ids = layers.map((l) => l.id);
  const lastStress = Math.max(...ids.map((id, i) => (id.startsWith("stress") ? i : -1)));
  assert.ok(lastStress >= 0);
  assert.ok(lastStress < ids.indexOf(RAIL_LAYERS.entrances), ids.join(" "));
  assert.ok(ids.indexOf(RAIL_LAYERS.elevators) < ids.indexOf(ROUTE_BOTTOM_LAYER));
});

test("the stations are added once, with an icon for every line combination and the elevator", () => {
  const { map, images, layers } = fakeMap([...BASE, ...ROUTE]);
  addRailStations(map, STATIONS, ALL, "#bdbadc", 2);
  const count = layers.length;
  assert.equal(addRailStations(map, STATIONS, ALL, "#bdbadc", 2), false);
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
  // Names only from street-ish zooms: below it the label is the empty string.
  assert.deepEqual(stations.layout["text-field"], ["step", ["zoom"], "", NAME_MIN_ZOOM, ["get", "name"]]);
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
  addRailStations(map, STATIONS, ALL, "#bdbadc", 2);
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
  addRailStations(map, STATIONS, ALL, "#bdbadc", 1);
  assert.deepEqual(
    layers.slice(-3).map((l) => l.id),
    [RAIL_LAYERS.entrances, RAIL_LAYERS.stations, RAIL_LAYERS.elevators],
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
