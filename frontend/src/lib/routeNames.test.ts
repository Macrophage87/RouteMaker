// The route's own street names (the owner, 2026-10-25: "Put the name of the road or path on the route itself"): the
// description's named stretches cut out of the line and named along it, in the street names' style.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { ROUTE_NAME_LAYER_ID, ROUTE_NAME_MIN_M, namedStretches, routeNameFeatures, routeNameLayer, routeNamePaint, sliceLine } from "./routeNames.ts";
import { RIDE_LABEL_LAYERS } from "./rideLabelOrder.ts";
import { ROAD_LABEL, TRAIL_LABEL } from "../stressStyle.js";

// A straight line east along the equator, about 1,113 m long (0.01 degrees), its vertices every 0.001 degrees.
const LINE: [number, number][] = Array.from({ length: 11 }, (_, i) => [i / 1000, 0]);

function stretch(from_m: number, to_m: number, street: string | null, facility: DescriptionEntry["facility"] = null): DescriptionEntry {
  return { kind: "stretch", from_m, to_m, street, facility } as DescriptionEntry;
}

function route(description: DescriptionEntry[]): Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description"> {
  return { geometry: { type: "LineString", coordinates: LINE }, distance_m: 1000, leg_ends: [0, LINE.length - 1], description };
}

test("each named stretch is cut out of the line, scaled from the description's metres to the line's", () => {
  const r = route([stretch(0, 500, "R Street Northwest"), stretch(500, 1000, "Rock Creek Trail", "path")]);
  const out = routeNameFeatures(r);
  assert.equal(out.features.length, 2);
  assert.deepEqual(out.features.map((f) => f.properties), [
    { name: "R Street Northwest", path: false },
    { name: "Rock Creek Trail", path: true },
  ]);
  // The description's 1,000 m is the line's full length, so the join is half way, at 0.005 degrees.
  const first = out.features[0].geometry.coordinates;
  assert.deepEqual(first[0], [0, 0]);
  assert.ok(Math.abs(first[first.length - 1][0] - 0.005) < 1e-9);
  assert.ok(Math.abs(out.features[1].geometry.coordinates[0][0] - 0.005) < 1e-9);
  assert.deepEqual(out.features[1].geometry.coordinates.at(-1), [0.01, 0]);
});

test("unnamed ways, junctions and other entries are not named", () => {
  const r = route([
    stretch(0, 300, "unnamed path"),
    stretch(300, 600, null),
    { ...stretch(600, 600, "Junction Street"), kind: "junction" } as DescriptionEntry,
    stretch(600, 1000, "this part of the route"),
  ]);
  assert.deepEqual(routeNameFeatures(r).features, []);
});

test("one street in several stretches is named as one; a stretch too short to hold its name is left out", () => {
  const r = route([stretch(0, 400, "16th Street Northwest"), stretch(400, 800, "16th Street Northwest"), stretch(800, 810, "Tiny Alley"), stretch(810, 1000, "U Street Northwest")]);
  const names = namedStretches(r).map((s) => s.name);
  assert.deepEqual(names, ["16th Street Northwest", "U Street Northwest"]);
  assert.ok(namedStretches(r).every((s) => s.toM - s.fromM >= ROUTE_NAME_MIN_M));
});

test("no route, no description or a greyed route: nothing named", () => {
  assert.deepEqual(routeNameFeatures(null).features, []);
  assert.deepEqual(routeNameFeatures(route([])).features, []);
});

test("sliceLine keeps the vertices inside and ends on the cut points", () => {
  const along = [0, 100, 200, 300];
  const coords: [number, number][] = [[0, 0], [1, 0], [2, 0], [3, 0]];
  assert.deepEqual(sliceLine(coords, along, 50, 250), [[0.5, 0], [1, 0], [2, 0], [2.5, 0]]);
});

test("the layer is in the street names' face, size and halo; the ride's size is theirs; a path is purple", () => {
  const plan = routeNameLayer("src", false, false);
  assert.equal(plan.layout["symbol-placement"], "line");
  assert.deepEqual(plan.layout["text-font"], [ROAD_LABEL.font]);
  assert.equal(plan.layout["text-size"], ROAD_LABEL.size);
  assert.equal(routeNameLayer("src", true, false).layout["text-size"], ROAD_LABEL.rideSize);
  assert.equal(plan.paint["text-halo-width"], ROAD_LABEL.haloWidth);
  assert.deepEqual(routeNamePaint(false)["text-color"], ["case", ["get", "path"], TRAIL_LABEL.color, ROAD_LABEL.color]);
  assert.deepEqual(routeNamePaint(true)["text-color"], ["case", ["get", "path"], TRAIL_LABEL.strongColor, ROAD_LABEL.strongColor]);
});

test("in a ride the route's names go up with the street names, on top of them", () => {
  assert.equal(RIDE_LABEL_LAYERS.at(-1), ROUTE_NAME_LAYER_ID);
});

test("MapView draws the names over the route line, under its hazard marks, and refreshes them with the route", () => {
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const at = (s: string) => mapView.indexOf(s);
  assert.ok(at('id: "route-line"') < at("routeNameLayer(ROUTE_NAME_SOURCE_ID") && at("routeNameLayer(ROUTE_NAME_SOURCE_ID") < at("routeHazardLayer()"));
  assert.match(mapView, /ROUTE_NAME_SOURCE_ID\) as GeoJSONSource \| undefined\)\?\.setData\(routeNameFeatures\(stale \? null : route\)/);
});
