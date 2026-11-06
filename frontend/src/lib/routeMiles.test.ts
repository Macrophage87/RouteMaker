// Mile markers on the route (the owner, 2026-11-06: "Put a dot on the route track every mile (or km in the case of
// metric) and every 5 miles put the mile number in a larger dot").
import { test } from "node:test";
import assert from "node:assert/strict";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import {
  KM_M,
  MILE_M,
  ROUTE_MILE_BIG_LAYER_ID,
  ROUTE_MILE_DOT_LAYER_ID,
  ROUTE_MILE_NUMBER_LAYER_ID,
  applyMileSizes,
  markerMinZooms,
  markerSizes,
  routeMileFeatures,
  routeMileLayers,
} from "./routeMiles.ts";
import { RIDE_LABEL_LAYERS } from "./rideLabelOrder.ts";

// A straight line east along the equator, 0.2 degrees (about 22.26 km, 13.8 mi), vertices every 0.01 degrees.
const LINE: [number, number][] = Array.from({ length: 21 }, (_, i) => [i / 100, 0]);
const LINE_M = 22263.9;

function route(distance: number, description: DescriptionEntry[] = []): Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description"> {
  return { geometry: { type: "LineString", coordinates: LINE }, distance_m: distance, leg_ends: [0, LINE.length - 1], description };
}

test("a dot every whole mile short of the finish, and every fifth is the big one with its number", () => {
  const out = routeMileFeatures(route(LINE_M), "us");
  // 22.26 km is 13.83 mi: markers 1..13.
  assert.deepEqual(out.features.map((f) => f.properties.n), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]);
  assert.deepEqual(out.features.filter((f) => f.properties.big).map((f) => f.properties.n), [5, 10]);
});

test("metric puts them every kilometre", () => {
  const out = routeMileFeatures(route(LINE_M), "metric");
  assert.equal(out.features.length, 22);
  assert.deepEqual(out.features.filter((f) => f.properties.big).map((f) => f.properties.n), [5, 10, 15, 20]);
});

test("the markers sit where the route's own distance says, scaled onto the line", () => {
  // The API says the route is half the line's length: mile 1 is two line-miles along.
  const out = routeMileFeatures(route(LINE_M / 2), "us");
  const lon = out.features[0].geometry.coordinates[0];
  const expected = ((2 * MILE_M) / LINE_M) * 0.2;
  assert.ok(Math.abs(lon - expected) < 1e-4, `${lon} vs ${expected}`);
  assert.equal(out.features.length, 6);
  // Unscaled, kilometre 1 is 1,000 m along: 0.008983 degrees at the equator.
  const km = routeMileFeatures(route(LINE_M), "metric").features[0].geometry.coordinates[0];
  assert.ok(Math.abs(km - (KM_M / LINE_M) * 0.2) < 1e-5);
});

test("the description's end is the route's length when it has one", () => {
  const description = [{ kind: "stretch", from_m: 0, to_m: 3 * MILE_M + 10, street: "R Street Northwest", facility: null } as DescriptionEntry];
  const out = routeMileFeatures(route(LINE_M, description), "us");
  assert.deepEqual(out.features.map((f) => f.properties.n), [1, 2, 3]);
});

test("no markers for no route, a one-point line or a route shorter than a mile", () => {
  assert.equal(routeMileFeatures(null, "us").features.length, 0);
  assert.equal(routeMileFeatures({ ...route(10), geometry: { type: "LineString", coordinates: [[0, 0]] } }, "us").features.length, 0);
  assert.equal(routeMileFeatures({ ...route(1500), geometry: { type: "LineString", coordinates: [[0, 0], [0.0134, 0]] } }, "us").features.length, 0);
});

test("zoomed out the small dots go first, metric's closer kilometres sooner", () => {
  const us = markerMinZooms("us");
  const metric = markerMinZooms("metric");
  assert.ok(us.dot > us.big);
  assert.ok(metric.dot > us.dot && metric.big > us.big);
  const layers = routeMileLayers("route-miles", false, false, "us");
  assert.deepEqual(layers.map((l) => [l.id, l.minzoom]), [
    [ROUTE_MILE_DOT_LAYER_ID, us.dot],
    [ROUTE_MILE_BIG_LAYER_ID, us.big],
    [ROUTE_MILE_NUMBER_LAYER_ID, us.big],
  ]);
});

test("larger in a ride and with the accessibility switch; the number always shows with its dot", () => {
  const plan = markerSizes(false, false);
  const ride = markerSizes(true, false);
  const strong = markerSizes(false, true);
  assert.ok(ride.big > plan.big && ride.text > plan.text);
  assert.ok(strong.ring > plan.ring && strong.dot > plan.dot && strong.text > plan.text);
  // The number fits its dot: its text no wider than the dot's diameter for two digits (~0.6 em each).
  for (const s of [plan, ride, strong]) assert.ok(2 * 0.6 * s.text <= 2 * s.big, JSON.stringify(s));
  const number = routeMileLayers("route-miles", false, false, "us")[2] as { layout: Record<string, unknown> };
  assert.equal(number.layout["text-allow-overlap"], true);
});

test("applyMileSizes re-sizes the layers in place", () => {
  const set: [string, string, unknown][] = [];
  const map = {
    getLayer: () => true,
    setPaintProperty: (id: string, name: string, value: unknown) => set.push([id, name, value]),
    setLayoutProperty: (id: string, name: string, value: unknown) => set.push([id, name, value]),
  };
  applyMileSizes(map, true, false);
  assert.deepEqual(set.find(([id, name]) => id === ROUTE_MILE_NUMBER_LAYER_ID && name === "text-size")?.[2], markerSizes(true, false).text);
  assert.deepEqual(set.find(([id, name]) => id === ROUTE_MILE_BIG_LAYER_ID && name === "circle-radius")?.[2], markerSizes(true, false).big);
});

test("in a ride the markers go up over the street names, the number on top", () => {
  const at = (id: string) => RIDE_LABEL_LAYERS.indexOf(id);
  assert.ok(at(ROUTE_MILE_DOT_LAYER_ID) > at("route-name"));
  assert.ok(at(ROUTE_MILE_NUMBER_LAYER_ID) > at(ROUTE_MILE_BIG_LAYER_ID));
});
