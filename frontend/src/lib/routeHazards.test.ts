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
import { SEVERITY_COLOURS } from "./intersectionMarkers.ts";
import {
  ROUTE_HAZARD_EDGE,
  ROUTE_HAZARD_FILL,
  ROUTE_HAZARD_KEY_NAME,
  ROUTE_HAZARD_KEY_SHAPE,
  ROUTE_HAZARD_KEY_TEXT,
  ROUTE_HAZARD_MARK,
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

test("the stress sections' traced length scales it where the route has them", () => {
  // The traced route twice the line's length: a stretch from 1,730 m traced starts at the line's middle.
  const out = routeHazardFeatures(route({ road_hazards: [{ ...RAILS, from_m: 1730, to_m: 3000 }], stress_spans: [{ from_m: 0, to_m: 3460 }] } as unknown as Partial<RouteResponse>));
  const coordinates = out.features[0].geometry.coordinates;
  assert.ok(Math.abs(coordinates[0][0] - -76.99) < 0.0015, `starts near the middle vertex, ${coordinates[0][0]}`);
  assert.ok(coordinates[coordinates.length - 1][0] < -76.98, "ends before the line does");
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

test("the mark's '!', disc and rim are told apart, and the icon is a disc", () => {
  assert.ok(contrastRatio(ROUTE_HAZARD_MARK, ROUTE_HAZARD_FILL) >= 7);
  assert.ok(contrastRatio(ROUTE_HAZARD_EDGE, ROUTE_HAZARD_FILL) >= 7);
  const icon = routeHazardIcon(2);
  assert.equal(icon.width, 36);
  const at = (x: number, y: number) => Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4));
  assert.equal(at(0, 0)[3], 0, "transparent outside the disc");
  assert.equal(at(18, 0)[3] > 0, true, "the disc reaches the top middle");
  assert.equal(at(1, 18)[3] > 0, true, "and the left middle, where a triangle would not");
  assert.deepEqual(at(18, 1).slice(0, 3), [0xff, 0xff, 0xff], "white rim");
  assert.deepEqual(at(8, 18).slice(0, 3), [0x11, 0x18, 0x27], "near-black inside");
  assert.deepEqual(at(18, 15).slice(0, 3), [0xfb, 0xbf, 0x24], "the amber bar");
});

test("the mark is not the higher-stress junction's: another shape, and dark where it is light", () => {
  // The owner, 2026-10-20: "the on a route marker looks identical to a higher stress intersection".
  const icon = routeHazardIcon(2);
  const at = (x: number, y: number) => icon.data[(y * icon.width + x) * 4 + 3];
  // The junction's triangle (SEVERITY_SHAPES.orange) leaves its upper left corner empty at mid height; the disc fills it.
  assert.ok(at(4, 12) > 0, "the disc fills where a triangle has none");
  for (const severity of ["orange", "red"] as const) assert.ok(contrastRatio(ROUTE_HAZARD_FILL, SEVERITY_COLOURS[severity].fill) >= 3, severity);
});

test("the announcement names each, and none says nothing", () => {
  assert.equal(roadHazardsSaid({ road_hazards: [] }), null);
  assert.equal(
    roadHazardsSaid({ road_hazards: [RAILS, { ...RAILS, kinds: ["cobbles", "rails"], road: "O Street Northwest" }] }),
    "This route rides 2 known hazards: rails in the road on H Street Northeast, cobblestones and rails in the road on O Street Northwest. The directions list them.",
  );
});

test("the key says what the mark means, in words, with the row's whole width", () => {
  const html = renderToStaticMarkup(createElement(RouteHazardKey));
  assert.match(html, /aria-hidden="true"/);
  assert.ok(html.includes(ROUTE_HAZARD_KEY_TEXT));
  assert.ok(html.includes(`${ROUTE_HAZARD_KEY_NAME}</span><span class="hint"> (${ROUTE_HAZARD_KEY_SHAPE}): </span>`));
  assert.match(html, /<circle /, "the swatch is the map's disc");
  assert.doesNotMatch(html, /polygon/, "not the old triangle");
  // Not the stress key's grid (68 px swatch, 52 px figure, then the words): that put the words in the 52 px column.
  assert.doesNotMatch(html, /class="legend[ "]/);
});

test("Ride says a hazard ahead, shortly, at every level but Quiet", () => {
  assert.equal(roadHazardWords(RAILS.text), "Rails in the road on H Street Northeast. Cross them square on, a wheel can drop into the groove.");
  assert.equal(roadHazardWords("Cobblestones on O Street Northwest, at 0.4 mi (0.6 km): bumpy, and slippery when wet."), "Cobblestones on O Street Northwest. Bumpy, and slippery when wet.");
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
