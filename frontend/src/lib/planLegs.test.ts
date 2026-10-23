/**
 * Plan's legs as planned (v0.10.0, Stephen 2026-10-20: "make it clear that manual mode is being used. Show faint
 * straight lines between points while being planned. Solid for routed, dashed for manual.").
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { planLegEdit, planLegLines, routeDrawnLines } from "./planLegs.ts";
import { insertIntoRide } from "./lineEdit.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];
const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a line from each point to the next, drawn where the leg is drawn by hand", () => {
  const lines = planLegLines([p(-77.0), p(-77.01), p(-77.02)], [1]);
  assert.deepEqual(
    lines.features.map((f) => [f.geometry.coordinates, f.properties.drawn]),
    [
      [[[-77.0, 38.9], [-77.01, 38.9]], false],
      [[[-77.01, 38.9], [-77.02, 38.9]], true],
    ],
  );
  assert.deepEqual(planLegLines([p(-77.0)], []).features, []);
});

test("a loop's lines close on the start, so the plan shows how the points connect (Stephen 2026-10-20)", () => {
  const lines = planLegLines([p(-77.0), p(-77.01), p(-77.02, 38.91)], [], true);
  assert.deepEqual(
    lines.features.map((f) => f.geometry.coordinates),
    [
      [[-77.0, 38.9], [-77.01, 38.9]],
      [[-77.01, 38.9], [-77.02, 38.91]],
      [[-77.02, 38.91], [-77.0, 38.9]],
    ],
  );
  // A loop of a start alone has no line; a start and one stop has the way out and the way back.
  assert.deepEqual(planLegLines([p(-77.0)], [], true).features, []);
  assert.equal(planLegLines([p(-77.0), p(-77.01)], [], true).features.length, 2);
});

test("the straight lines drag as the route does: one segment a leg, and a drag, not a click, adds the via", () => {
  const points = [p(-77.0), p(-77.01), p(-77.02)];
  const edit = planLegEdit(points, false);
  assert.deepEqual(edit?.ends, [1, 2]);
  assert.equal(edit?.points, points, "the same list, so a drop after an edit is refused (lineEdit.ts dropStillValid)");
  assert.equal(edit?.dragOnly, true);
  const loop = planLegEdit(points, true);
  assert.deepEqual(loop?.ends, [1, 2, 3]);
  assert.deepEqual(loop?.path.at(-1), points[0]);
  assert.equal(planLegEdit([p(-77.0)], true), null);
  // A drop on the closing leg of a loop appends the via, as a drop on a loop's route does.
  assert.deepEqual(insertIntoRide(points, 2, p(-77.03), true), [...points, p(-77.03)]);
  const map = source("../MapView.tsx");
  assert.match(map, /line: callbacks\.current\.lineEdit\?\.dragOnly \? null : lineAt\(/);
  assert.match(map, /id: "plan-legs-arrows",[\s\S]{0,120}"symbol-placement": "line"/);
});

test("the route's drawn legs are cut from its line at their leg ends", () => {
  const coordinates = [p(-77.0), p(-77.005, 38.91), p(-77.01), p(-77.02)];
  const lines = routeDrawnLines({ geometry: { coordinates }, leg_ends: [2, 3], drawn_legs: [1] }, 3);
  assert.deepEqual(lines.features.map((f) => f.geometry.coordinates), [[[-77.01, 38.9], [-77.02, 38.9]]]);
  const first = routeDrawnLines({ geometry: { coordinates }, leg_ends: [2, 3], drawn_legs: [0] }, 3);
  assert.equal(first.features[0].geometry.coordinates.length, 3);
  // No drawn legs, or leg ends that do not fit the line: none.
  assert.deepEqual(routeDrawnLines({ geometry: { coordinates }, leg_ends: [2, 3], drawn_legs: null }, 3).features, []);
  assert.deepEqual(routeDrawnLines({ geometry: { coordinates }, leg_ends: [2, 9], drawn_legs: [1] }, 3).features, []);
  // Leg ends for other points than the plan's (a router's own legs): none.
  assert.deepEqual(routeDrawnLines({ geometry: { coordinates }, leg_ends: [1, 2, 3], drawn_legs: [1] }, 3).features, []);
  assert.deepEqual(routeDrawnLines(null, 0).features, []);
});

test("the map shows the plan's lines only without a route for the points, and Plan shows that manual mode is on", () => {
  const map = source("../MapView.tsx");
  assert.match(map, /props\.planLegs && \(!props\.route \|\| props\.stale\)/);
  assert.match(map, /routeDrawnLines\(stale \? null : route, props\.points\.length\)/);
  assert.match(map, /filter: \["get", "drawn"\],[\s\S]{0,200}"line-dasharray": DRAWN_DASH/);
  const app = source("../App.tsx");
  // A loop's lines too (none drawn by hand), with its way back to the start (Stephen 2026-10-20).
  assert.match(app, /planLegs=\{riding \|\| reviewing \|\| mode !== "plan" \? null : loopVias \? NO_LEGS : planDrawn\}/);
  assert.match(app, /\{manual && <p className="plan-bar-manual-badge"><span>\{MANUAL_BADGE\}<\/span><\/p>\}/);
});
