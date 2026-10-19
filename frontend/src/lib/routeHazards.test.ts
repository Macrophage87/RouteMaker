// v0.10.0's route hazard marks (lib/routeHazards.ts). The owner, 2026-10-19: "We should have a symbol for roads with
// known other hazards on the map" and "You only need to show it if it's routed on".
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { contrastRatio } from "../stressStyle.js";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { rideModel, roadHazardWords, says } from "./navigate.ts";
import {
  ROUTE_HAZARD_EDGE,
  ROUTE_HAZARD_FILL,
  ROUTE_HAZARD_KEY_TEXT,
  ROUTE_HAZARD_SOURCE,
  RouteHazardKey,
  roadHazardsSaid,
  routeHazardFeatures,
  routeHazardIcon,
  routeHazardLayer,
  routeHazardRepeatLayer,
} from "./routeHazards.ts";

const LINE: [number, number][] = [
  [-77.0, 38.9],
  [-76.99, 38.9],
  [-76.98, 38.9],
];
const RAILS = { from_m: 400, to_m: 900, kinds: ["rails" as const], road: "H Street Northeast", text: "Rails in the road on H Street Northeast, 0.2 to 0.6 mi (0.4 to 0.9 km): cross them square on, a wheel can drop into the groove." };

function route(extra: Partial<RouteResponse> = {}): RouteResponse {
  return { geometry: { type: "LineString", coordinates: LINE }, distance_m: 1730, ...extra } as RouteResponse;
}

test("each hazard stretch is cut from the route's own line, scaled to it", () => {
  const out = routeHazardFeatures(route({ road_hazards: [RAILS] }));
  assert.equal(out.features.length, 1);
  const [first, ...rest] = out.features[0].geometry.coordinates;
  const last = rest[rest.length - 1];
  assert.ok(first[0] > -77.0 && first[0] < -76.99, "starts inside the first piece");
  assert.ok(last[0] > -76.99 && last[0] < -76.98, "ends inside the second");
  assert.ok(out.features[0].geometry.coordinates.some((c) => c[0] === -76.99), "keeps the vertex between");
  assert.equal(out.features[0].properties.kinds, "rails");
});

test("no hazards, or no route, draws nothing", () => {
  assert.deepEqual(routeHazardFeatures(route()).features, []);
  assert.deepEqual(routeHazardFeatures(route({ road_hazards: [] })).features, []);
  assert.deepEqual(routeHazardFeatures(null).features, []);
});

test("the layers are valid over their source and draw the icon", () => {
  const layers = [routeHazardLayer(), routeHazardRepeatLayer()];
  const errors = spec.validateStyleMin({ version: 8, sources: { [ROUTE_HAZARD_SOURCE]: { type: "geojson", data: { type: "FeatureCollection", features: [] } } }, layers } as never);
  assert.deepEqual(errors, []);
});

test("the mark's edge and fill are told apart, and the icon has both", () => {
  assert.ok(contrastRatio(ROUTE_HAZARD_FILL, ROUTE_HAZARD_EDGE) >= 7);
  const icon = routeHazardIcon(2);
  assert.equal(icon.width, 36);
  const at = (x: number, y: number) => Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4));
  assert.equal(at(0, 0)[3], 0, "transparent outside the triangle");
  assert.deepEqual(at(11, 28).slice(0, 3), [0xfb, 0xbf, 0x24], "amber inside");
  assert.deepEqual(at(18, 20).slice(0, 3), [0x11, 0x18, 0x27], "the mark's bar");
});

test("the announcement names each, and none says nothing", () => {
  assert.equal(roadHazardsSaid({ road_hazards: [] }), null);
  assert.equal(
    roadHazardsSaid({ road_hazards: [RAILS, { ...RAILS, kinds: ["cobbles", "rails"], road: "O Street Northwest" }] }),
    "This route rides 2 known hazards: rails in the road on H Street Northeast, cobblestones and rails in the road on O Street Northwest. The directions list them.",
  );
});

test("the key says what the mark means, in words", () => {
  const html = renderToStaticMarkup(createElement(RouteHazardKey));
  assert.match(html, /aria-hidden="true"/);
  assert.ok(html.includes(ROUTE_HAZARD_KEY_TEXT));
});

test("Ride says a hazard ahead, shortly, at every level but Quiet", () => {
  assert.equal(roadHazardWords(RAILS.text), "Rails in the road on H Street Northeast. Cross them square on, a wheel can drop into the groove.");
  assert.equal(roadHazardWords("Something else."), "Something else.");
  const entry: DescriptionEntry = { kind: "hazard", from_m: 400, to_m: 900, from_mi: 0.25, to_mi: 0.56, street: "H Street Northeast", tier: null, facility: null, turn: null, text: RAILS.text };
  const model = rideModel(route({ description: [entry], duration_s: 300, leg_ends: [2] }));
  const cue = model.cues.find((c) => c.source === "hazard");
  assert.ok(cue, "a cue");
  assert.equal(cue.kind, "hazard");
  assert.equal(cue.rideText, roadHazardWords(RAILS.text));
  assert.equal(says("stoker", cue), true);
  assert.equal(says("quiet", cue), false);
});
