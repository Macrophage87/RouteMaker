import { test } from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { ViaMarks } from "./pointKinds.ts";
import {
  RESET_NOTHING,
  ROUTE_NEEDS_POINTS,
  ROUTE_NEEDS_STOP,
  ROUTE_UP_TO_DATE,
  changeSummary,
  elapsedText,
  legChanges,
  planChanged,
  planSentences,
  routeButton,
  routingStep,
  sentencesText,
} from "./planFirst.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];
const words = { ride: "Default", traffic: "Balanced", hills: "Avoids hills" };

test("the plan reads as sentences: start, stops, via points, end, then the ride", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), marks.via(p(-77.01)), p(-77.02), p(-77.03), p(-77.04)];
  const names = new Map<LonLat, string>([
    [points[0], "Union Station"],
    [points[1], "Rock Creek Trail"],
    [points[2], "Eastern Market"],
    [points[3], "Union Market"],
    [points[4], "Silver Spring"],
  ]);
  const sentences = planSentences(points, marks.isVia, false, (q) => names.get(q), words);
  assert.equal(
    sentencesText(sentences),
    "Start at Union Station. Stop at Eastern Market, then Union Market. Pass through Rock Creek Trail (via). End at Silver Spring. Default ride, balanced, avoids hills.",
  );
  // Each name links to its point; the ride type and each slider to their editors.
  const targets = sentences.flat().flatMap((phrase) => (phrase.target ? [phrase.target] : []));
  assert.deepEqual(targets, [
    { kind: "point", index: 0 },
    { kind: "point", index: 2 },
    { kind: "point", index: 3 },
    { kind: "point", index: 1 },
    { kind: "point", index: 4 },
    { kind: "ride" },
    { kind: "traffic" },
    { kind: "hills" },
  ]);
});

test("an unfinished plan says what to do next, and a loop starts and finishes at its start", () => {
  const none = new ViaMarks().isVia;
  assert.equal(sentencesText(planSentences([], none, false, () => undefined, { ride: "Default", traffic: null, hills: null })), "Start: tap the map or search for a place. Default ride.");
  assert.equal(
    sentencesText(planSentences([p(-77)], none, false, () => undefined, words)),
    "Start at a point on the map. End: tap the map or search for a place. Default ride, balanced, avoids hills.",
  );
  assert.equal(
    sentencesText(planSentences([p(-77), p(-77.1)], none, true, () => "Here", words)),
    "Start and finish at Here. Stop at Here. Default ride, balanced, avoids hills.",
  );
});

test("the Route button: Route, then Update route after a change; unavailable with its reason", () => {
  assert.deepEqual(routeButton({ points: 1, drawn: false, changed: false, routeShown: false }), { label: "Route", unavailable: ROUTE_NEEDS_POINTS });
  // A loop needs a stop, not an end.
  assert.deepEqual(routeButton({ points: 1, drawn: false, changed: false, routeShown: false, loop: true }), { label: "Route", unavailable: ROUTE_NEEDS_STOP });
  assert.deepEqual(routeButton({ points: 2, drawn: false, changed: false, routeShown: false }), { label: "Route", unavailable: null });
  assert.deepEqual(routeButton({ points: 2, drawn: true, changed: false, routeShown: true }), { label: "Route", unavailable: ROUTE_UP_TO_DATE });
  assert.deepEqual(routeButton({ points: 3, drawn: true, changed: true, routeShown: true }), { label: "Update route", unavailable: null });
  assert.equal(RESET_NOTHING, "Nothing changed since the route was drawn");
});

test("a change is measured against the plan the route was drawn for", () => {
  const points = [p(-77), p(-77.1)];
  const drawn = { points, ride: { preset: "default" }, dialsKey: "k" };
  assert.equal(planChanged(null, points, "default", "k"), false);
  assert.equal(planChanged(drawn, points, "default", "k"), false);
  assert.equal(planChanged(drawn, [...points], "default", "k"), true);
  assert.equal(planChanged(drawn, points, "novice", "k"), true);
  assert.equal(planChanged(drawn, points, "default", "k2"), true);
});

test("routing shows its step in words and the seconds elapsed", () => {
  assert.deepEqual([0, 2000, 5000, 12000].map(routingStep), ["Finding routes", "Checking traffic stress", "Ranking", "Drawing"]);
  assert.equal(elapsedText(3400), "3 s");
});

const stretch = (street: string, from: number, to: number): DescriptionEntry =>
  ({ kind: "stretch", from_m: from, to_m: to, from_mi: 0, to_mi: 0, street, text: "" }) as unknown as DescriptionEntry;
const route = (distance: number, seconds: number, busy: number, ...streets: [string, number][]): Pick<RouteResponse, "distance_m" | "duration_s" | "stress_m" | "description"> => {
  let at = 0;
  return {
    distance_m: distance,
    duration_s: seconds,
    stress_m: { "1": distance - busy, "3": busy },
    description: streets.map(([name, metres]) => stretch(name, at, (at += metres))),
  };
};

test("an update says what changed in one line, US units first", () => {
  const before = route(8000, 1800, 1000, ["16th Street Northwest", 3000], ["Park Road", 5000]);
  const after = route(9931, 2160, 356, ["Beach Drive", 4000], ["Park Road", 5931]);
  assert.equal(
    changeSummary(before, after),
    "+1.2 mi (1.9 km), +6 min, 0.4 mi (0.6 km) less on LTS 3 or busier, now uses Beach Drive instead of 16th Street Northwest.",
  );
  assert.equal(changeSummary(before, before), "The same route as before.");
  assert.equal(changeSummary(after, before).startsWith("−1.2 mi (1.9 km), −6 min, 0.4 mi (0.6 km) more on LTS 3 or busier"), true);
});

test("the per-leg details: each leg's length and change, new legs, and legs no longer ridden, US units first", () => {
  const a = p(-77.0);
  const b = p(-77.01);
  const c = p(-77.02);
  const d = p(-77.03);
  const names = new Map<LonLat, string>([[a, "Union Market"], [c, "The Wharf"]]);
  const nameOf = (q: LonLat) => names.get(q);
  const isVia = () => false;
  const line = (coordinates: LonLat[], leg_ends: number[]) => ({ geometry: { type: "LineString", coordinates }, leg_ends }) as unknown as Pick<RouteResponse, "geometry" | "leg_ends">;
  const before = { points: [a, b, c], loop: false, route: line([a, b, c], [1, 2]) };
  // The same first leg, ridden the long way round; the second now goes to d instead of c.
  const after = { points: [a, b, d], loop: false, route: line([a, p(-77.005, 38.91), b, d], [2, 3]) };
  const lines = legChanges(before, after, isVia, nameOf);
  assert.equal(lines.length, 3);
  assert.match(lines[0], /^Start \(Union Market\) to Stop 1: \d+\.\d mi \(\d+\.\d km\), \+\d+\.\d mi \(\d+\.\d km\)\.$/);
  assert.match(lines[1], /^Stop 1 to End: \d+\.\d mi \(\d+\.\d km\), a new leg\.$/);
  assert.match(lines[2], /^Stop 1 to End \(The Wharf\): no longer ridden \(was \d+\.\d mi \(\d+\.\d km\)\)\.$/);
  // The same plan again: every leg unchanged.
  assert.deepEqual(
    legChanges(before, before, isVia, nameOf).map((l) => l.replace(/\d+\.\d mi \(\d+\.\d km\)/, "N")),
    ["Start (Union Market) to Stop 1: N, unchanged.", "Stop 1 to End (The Wharf): N, unchanged."],
  );
  // Legs that do not fit the points (an older API): no details rather than wrong ones.
  assert.deepEqual(legChanges(before, { ...after, route: line([a, b, d], [2]) }, isVia, nameOf), []);
});

test("an empty plan has Start at current location in Route's place, and From keeps it in its list only", () => {
  const panel = readFileSync(new URL("../app/PlanPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /export const START_HERE_LABEL = "Start at current location";/);
  assert.match(panel, /\{locate \? \([\s\S]{0,200}className="route-button start-here"[\s\S]{0,120}onClick=\{locate\.onLocate\}/);
  // Why Route is unavailable is said with it, not shown (Stephen 2026-10-20: simpler).
  assert.match(panel, /<span id=\{routeWhy\} className="visually-hidden">/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /locate=\{points\.length === 0 && locateReady\.available \? \{ onLocate: \(\) => void useMyLocation\("start"\), busy: locating \} : null\}/);
  const planner = readFileSync(new URL("../app/Planner.tsx", import.meta.url), "utf8");
  assert.match(planner, /listOnly: variant === "add" \|\| \(variant === "from" && points\.length === 0\),/);
});
