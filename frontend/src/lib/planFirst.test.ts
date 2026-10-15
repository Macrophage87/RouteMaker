import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { ViaMarks } from "./pointKinds.ts";
import {
  RESET_NOTHING,
  ROUTE_NEEDS_POINTS,
  ROUTE_UP_TO_DATE,
  changeSummary,
  elapsedText,
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
