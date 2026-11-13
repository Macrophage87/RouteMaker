/** Plan's Keep to compare (lib/compareRoutes.ts; the backlog's "choose between routes in Plan", 2026-11-13). */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { RouteResponse } from "./api.ts";
import { compareRows, sameRoute } from "./compareRoutes.ts";
import { compareBlock, type PlanCompare } from "./compareBlock.ts";

function body(over: Partial<RouteResponse> = {}): RouteResponse {
  return {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [[-77, 38.9], [-77.01, 38.91]] },
    distance_m: 16_093,
    duration_s: 3_600,
    climb_m: 100,
    descent_m: 100,
    stress_m: { "1": 12_000, "2": 3_000, "3": 1_000, "4": 93 },
    facility_m: { path: 5_000 },
    intersections: [{ severity: "red" }, { severity: "orange" }] as never,
    attribution: [],
    ...over,
  } as RouteResponse;
}

test("the rows: time and distance always, the rest only where either route has some, the better side marked", () => {
  const kept = body();
  const now = body({ duration_s: 3_300, distance_m: 17_000, stress_m: { "1": 17_000 }, intersections: [], facility_m: { path: 9_000 } });
  const rows = compareRows(kept, now);
  const labels = rows.map((r) => r.label);
  assert.deepEqual(labels, ["Time", "Distance", "Climb", "Busy roads", "Heavy traffic", "Stressful junctions", "Paths and protected lanes"]);
  const by = Object.fromEntries(rows.map((r) => [r.label, r]));
  assert.equal(by["Time"].better, "now", "five minutes faster");
  assert.equal(by["Distance"].better, "kept", "shorter");
  assert.equal(by["Climb"].better, null, "the same climb");
  assert.equal(by["Busy roads"].better, "now");
  assert.equal(by["Stressful junctions"].kept, "2");
  assert.equal(by["Stressful junctions"].now, "0");
  assert.equal(by["Paths and protected lanes"].better, "now", "more path is better");
  assert.match(by["Distance"].kept, /^10\.0 mi/, "miles first");
});

test("a difference too small to say is no better on either side, and both-zero rows are left out", () => {
  const rows = compareRows(body({ stress_m: { "1": 16_093 } }), body({ duration_s: 3_630, stress_m: { "1": 16_093 } }));
  assert.equal(rows.find((r) => r.label === "Time")?.better, null, "30 s is the same time");
  assert.equal(rows.find((r) => r.label === "Busy roads"), undefined);
});

test("a figure an older API leaves out is no row", () => {
  const rows = compareRows(body({ description: undefined }), body());
  assert.equal(rows.find((r) => r.label === "Turns"), undefined);
  assert.equal(rows.find((r) => r.label === "Waiting at lights"), undefined);
});

test("the same route put back through the planner is the same route", () => {
  assert.ok(sameRoute(body(), body()));
  assert.ok(!sameRoute(body(), body({ distance_m: 16_200 })));
});

const panel = (compare: PlanCompare) => {
  const block = compareBlock(compare);
  return block ? renderToStaticMarkup(createElement("div", null, block)) : "";
};
const noop = () => {};

test("the panel: one Keep to compare button while nothing is kept, none while the plan is changed", () => {
  const html = panel({ rows: null, kept: false, edited: false, onKeep: noop, onUse: noop, onStop: noop });
  assert.match(html, />Keep to compare</);
  assert.doesNotMatch(html, /Stop comparing/);
  assert.doesNotMatch(panel({ rows: null, kept: false, edited: true, onKeep: noop, onUse: noop, onStop: noop }), /Keep to compare/);
});

test("the panel: with a route kept, the table with its better cells said, Use kept route and Stop comparing", () => {
  const rows = compareRows(body(), body({ duration_s: 3_000 }));
  const html = panel({ rows, kept: true, edited: false, onKeep: noop, onUse: noop, onStop: noop });
  assert.match(html, /<table class="plan-compare-table">/);
  assert.match(html, /<th scope="col">Kept<\/th><th scope="col">Now<\/th>/);
  assert.match(html, /class="plan-compare-better">50 min<span class="visually-hidden">, better<\/span>/);
  assert.match(html, />Use kept route</);
  assert.match(html, />Stop comparing</);
  assert.doesNotMatch(html, /Keep to compare/);
  // The route shown is the kept one: a hint, no table, no Use kept route.
  const same = panel({ rows: null, kept: true, edited: false, onKeep: noop, onUse: noop, onStop: noop });
  assert.match(same, /This is the kept route/);
  assert.doesNotMatch(same, /Use kept route/);
  assert.match(panel({ rows: null, kept: true, edited: true, onKeep: noop, onUse: noop, onStop: noop }), /dashed on the map/);
});

test("App: the kept route is the map's dashed line while comparing, and going back answers with the kept route itself", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /planFirst && keptDashed && compareKept \? compareKept\.route\.geometry\.coordinates : null/);
  assert.match(app, /savedShown\.current = \{ key: keptPlanKey\(back\.drawn\.points, back\.drawn\.ride\.preset, back\.dials\), answer: back\.route, once: true \}/);
  // Answered once, then gone: a later change its key does not cover is planned afresh (the review's 1).
  assert.match(app, /if \(saved\.once\) savedShown\.current = null;/);
  // Another plan opened drops it (the review's 4).
  assert.match(app, /const forgetDrawn = \(\) => \{\s*\/\/[^\n]*\n\s*setCompareKept\(null\);/);
  // Clear drops it; a change of plan does not.
  assert.match(app, /const clearPlan = \(\) => \{\n\s+setCompareKept\(null\);/);
});

test("styles.css closes every rule it opens (a merge once left one open, nesting the compare and loop rules inside it)", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.equal((css.match(/\{/g) ?? []).length, (css.match(/\}/g) ?? []).length);
  assert.match(css, /\n\.plan-compare \{/);
  assert.match(css, /\n\.loop-way\.chosen \{/);
});
