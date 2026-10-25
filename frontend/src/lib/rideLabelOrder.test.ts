// Every street named in a ride (the owner, 2026-10-24): the street and trail names lifted under the station names
// for the ride and put back after, run against a stand-in map that keeps its layers in draw order as MapLibre does.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RIDE_LABEL_LAYERS, labelHomes, rideLabelsTarget, setRideLabelOrder, type LabelHomes } from "./rideLabelOrder.ts";

// The order a ride's map has, bottom first: the base map's labels low, the overlay's trail names under them, the
// shops' names, the place names, the water icons and the route over them, the station names and hazards on top.
const MAP = [
  "roads_minor",
  "stress-tier-1",
  "trail-name",
  "roads_oneway",
  "roads_labels_minor",
  "water_label_ocean",
  "roads_shields",
  "roads_labels_major",
  "pois",
  "places_subplace",
  "water-restrooms",
  "route-casing",
  "route-line",
  "rail-station-names",
  "route-hazard-marks",
  "route-hazard-marks-along",
];

function fakeMap(initial: readonly string[]) {
  const layers = [...initial];
  return {
    layers,
    moves: 0,
    getLayersOrder: () => [...layers],
    getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
    moveLayer(id: string, before?: string) {
      this.moves += 1;
      layers.splice(layers.indexOf(id), 1);
      layers.splice(before === undefined ? layers.length : layers.indexOf(before), 0, id);
    },
  };
}

test("in a ride the street and trail names go directly under the station names, trails lowest", () => {
  const map = fakeMap(MAP);
  setRideLabelOrder(map, true, new Map());
  const at = (id: string) => map.layers.indexOf(id);
  assert.deepEqual(map.layers.slice(at("trail-name"), at("rail-station-names") + 1), ["trail-name", "roads_labels_minor", "roads_labels_major", "rail-station-names"]);
  // Over everything that took a street name's spot before: shops, place names, water icons; and over the route.
  for (const under of ["pois", "places_subplace", "water-restrooms", "route-line"]) assert.ok(at(under) < at("trail-name"), under);
  // The hazard marks stay on top.
  assert.ok(at("route-hazard-marks-along") > at("roads_labels_major"));
});

test("lifted already, nothing moves", () => {
  const map = fakeMap(MAP);
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  const moves = map.moves;
  assert.equal(rideLabelsTarget(map.getLayersOrder()), null);
  setRideLabelOrder(map, true, homes);
  assert.equal(map.moves, moves);
});

test("a layer added on top during the ride (the route) is put under the names again, under the station names", () => {
  const map = fakeMap(MAP.filter((id) => id !== "rail-station-names" && !id.startsWith("route-hazard")));
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  assert.deepEqual(map.layers.slice(-3), ["trail-name", "roads_labels_minor", "roads_labels_major"]);
  map.layers.push("route-new", "rail-station-names");
  setRideLabelOrder(map, true, homes);
  assert.deepEqual(map.layers.slice(-5), ["route-new", "trail-name", "roads_labels_minor", "roads_labels_major", "rail-station-names"]);
});

test("after the ride every name is back where the base map put it", () => {
  const map = fakeMap(MAP);
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  assert.notDeepEqual(map.layers, MAP);
  setRideLabelOrder(map, false, homes);
  assert.deepEqual(map.layers, MAP);
  assert.equal(homes.size, 0);
});

test("a label that comes during the ride (the overlay's trail names, late) is lifted and put home too", () => {
  const late = MAP.filter((id) => id !== "trail-name");
  const map = fakeMap(late);
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  map.layers.splice(map.layers.indexOf("roads_oneway"), 0, "trail-name");
  setRideLabelOrder(map, true, homes);
  assert.equal(map.layers[map.layers.indexOf("rail-station-names") - 3], "trail-name");
  assert.equal(setRideLabelOrder(map, false, homes), true);
  assert.deepEqual(map.layers, MAP);
});

test("a home gone by the ride's end leaves that label where it is and the rest go home", () => {
  const map = fakeMap(MAP);
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  map.layers.splice(map.layers.indexOf("pois"), 1);
  setRideLabelOrder(map, false, homes);
  assert.equal(map.layers[map.layers.indexOf("water_label_ocean") - 1], "roads_labels_minor");
  assert.equal(map.layers[map.layers.indexOf("roads_oneway") - 1], "trail-name");
  assert.equal(homes.size, 0);
});

test("outside a ride nothing is lifted", () => {
  const map = fakeMap(MAP);
  setRideLabelOrder(map, false, new Map());
  assert.deepEqual(map.layers, MAP);
  assert.equal(map.moves, 0);
});

test("a home is the next layer up; the names only lifted are left out", () => {
  const homes = labelHomes(MAP);
  assert.equal(homes.get("trail-name"), "roads_oneway");
  assert.equal(homes.get("roads_labels_minor"), "water_label_ocean");
  assert.equal(homes.get("roads_labels_major"), "pois");
  assert.deepEqual(RIDE_LABEL_LAYERS, ["trail-name", "roads_labels_minor", "roads_labels_major", "route-name"]);
  assert.equal(rideLabelsTarget(["a", "b"]), null);
});

test("MapView lifts the names with the ride's labels and keeps the climbs under the route", () => {
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(mapView, /if \(setRideLabelOrder\(map, riding, labelHomes\.current\)\) climbsUnder\(map, TRAIL_LABEL_LAYER_ID\)/);
  assert.match(mapView, /\(!lifted && layerIds\.find\(.*\)\) \|\| ROUTE_BOTTOM_LAYER/);
});

test("the route's own names (lib/routeNames.ts) go up on top of the street names, and back over the route after", () => {
  const start = ["roads_labels_minor", "roads_labels_major", "pois", "route-line", "route-name", "rail-station-names", "route-hazard-marks"];
  const map = fakeMap(start);
  const homes: LabelHomes = new Map();
  setRideLabelOrder(map, true, homes);
  assert.deepEqual(map.layers, ["pois", "route-line", "roads_labels_minor", "roads_labels_major", "route-name", "rail-station-names", "route-hazard-marks"]);
  setRideLabelOrder(map, false, homes);
  assert.deepEqual(map.layers, start);
});
