/**
 * Plan's manual mode (v0.9.1, Stephen 2026-10-19: "a 'manual mode' where you can just route directly"): the legs
 * drawn as straight lines, kept on the points (lib/pointKinds.ts), in the link and saved routes (`line=`), and sent
 * to the API (`straight_legs`, core/routing.py `_drawn`).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { VIA_MARKS, ViaMarks, decodeDrawn, drawnLegs, viaIndices } from "./pointKinds.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { routeRequestBody } from "./api.ts";
import { startDials } from "./dials.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];
const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a drawn leg is the leg that ends at a marked point", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), p(-77.01), marks.drawn(p(-77.02)), p(-77.03)];
  assert.deepEqual(drawnLegs(points, marks.isDrawn), [1]);
  // A mark on the start draws nothing: no leg ends there.
  assert.deepEqual(drawnLegs([marks.drawn(p(-77.1)), p(-77.2)], marks.isDrawn), []);
});

test("moving a point or switching its kind keeps its leg drawn", () => {
  const marks = new ViaMarks();
  const drawn = marks.via(marks.drawn(p(-77.02)));
  const moved = marks.moved(drawn, p(-77.025));
  assert.ok(marks.isDrawn(moved) && marks.isVia(moved));
  const stop = marks.withKind(drawn, "stop");
  assert.ok(marks.isDrawn(stop) && !marks.isVia(stop));
});

test("an added point is drawn to in manual mode, or where it splits a drawn leg; other edits change no mark", () => {
  const marks = new ViaMarks();
  const a = p(-77.0);
  const c = marks.drawn(p(-77.02));
  const b = p(-77.01);
  // Splitting the drawn leg a-c: both halves drawn.
  assert.deepEqual(drawnLegs(marks.afterEdit([a, c], [a, b, c], false), marks.isDrawn), [0, 1]);
  // Splitting a routed leg, manual mode off: routed.
  const d = p(-77.03);
  const e = p(-77.04);
  assert.deepEqual(drawnLegs(marks.afterEdit([a, d], [a, e, d], false), marks.isDrawn), []);
  // Manual mode: the line to the new point is drawn; a new start has none.
  const f = p(-77.05);
  assert.deepEqual(drawnLegs(marks.afterEdit([a, d], [a, d, f], true), marks.isDrawn), [1]);
  const g = p(-77.06);
  marks.afterEdit([a], [g, a], true);
  assert.ok(!marks.isDrawn(g));
  // A move (same length) changes nothing, even in manual mode.
  const h = p(-77.07);
  marks.afterEdit([a, d], [a, h], true);
  assert.ok(!marks.isDrawn(h));
});

test("withLegs draws exactly the legs asked, keeping each point's kind and the pairs that need no change", () => {
  const marks = new ViaMarks();
  const a = p(-77.0);
  const b = marks.via(p(-77.01));
  const c = marks.drawn(p(-77.02));
  const out = marks.withLegs([a, b, c], [0]);
  assert.equal(out[0], a);
  assert.notEqual(out[1], b);
  assert.ok(marks.isDrawn(out[1]) && marks.isVia(out[1]));
  assert.ok(!marks.isDrawn(out[2]));
  assert.deepEqual(drawnLegs(out, marks.isDrawn), [0]);
});

test("the link keeps the drawn legs, and an older link has none", () => {
  const points = [p(-77.0), p(-77.01), p(-77.02)];
  const hash = encodePlan(points, "default", startDials("default"), [], [1]);
  assert.match(hash, /line=1(&|$)/);
  const plan = decodePlan(hash);
  assert.deepEqual(plan.drawn, [1]);
  assert.deepEqual(decodePlan(hash.replace(/&?line=1/, "")).drawn, []);
  // Out of range, repeated or not a number: left out.
  assert.deepEqual(decodeDrawn("1,1,-1,2,x,0", 3), [0, 1]);
});

test("the link reads the page's marks when it is not told the legs: a saved route's or kept route's key has them", () => {
  const points = [p(-77.0), VIA_MARKS.drawn(p(-77.01))];
  assert.match(encodePlan(points, "default", startDials("default")), /line=0/);
  const again = decodePlan(encodePlan(points, "default", startDials("default")));
  VIA_MARKS.markDrawn(again.points, again.drawn);
  assert.deepEqual(drawnLegs(again.points), [0]);
});

test("the route request sends the drawn legs, but never on a two-point ride type", () => {
  const points = [p(-77.0), p(-77.01), p(-77.02)];
  const body = JSON.parse(routeRequestBody(points, "default", { straight: [0] }));
  assert.deepEqual(body.straight_legs, [0]);
  assert.equal(JSON.parse(routeRequestBody(points, "default", { straight: [] })).straight_legs, undefined);
  assert.equal(JSON.parse(routeRequestBody(points.slice(0, 2), "bikeshare", { straight: [0] })).straight_legs, undefined);
});

test("Plan's map bar has the switch, and the page sends and keeps the drawn legs", () => {
  const app = source("../App.tsx");
  assert.match(app, /aria-pressed=\{manual\}/);
  assert.match(app, /straight: drawnLegs\(plan\.points\)/);
  // Every edit goes through commit, which marks an added point (afterEdit); a manual tap is the new end.
  assert.match(app, /edits\.commit\(VIA_MARKS\.afterEdit\(pointsRef\.current, next, manualRef\.current\), ride\)/);
  assert.match(app, /manualRef\.current && current\.length >= 1\s*\? \[\.\.\.current\.slice\(0, -1\)/);
  // Ride's re-plan keeps them.
  assert.match(source("../RideMode.tsx"), /straight: drawnLegs\(to\)/);
  assert.match(app, /VIA_MARKS\.markDrawn\(initialPlan\.points, initialPlan\.drawn\)/);
  // Only in Plan, and not on a loop or a two-point ride type.
  assert.match(app, /const manualOffered = mode === "plan" && !loopVias && !twoPointsOnly\(preset\);/);
  // viaIndices is untouched by the drawn marks.
  const marks = new ViaMarks();
  assert.deepEqual(viaIndices([p(0), marks.drawn(p(1)), p(2)], marks.isVia), []);
});
